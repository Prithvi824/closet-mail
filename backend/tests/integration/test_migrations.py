"""Migrations round-trip on a scratch database and match the ORM models."""

# 1st party imports
import asyncio
import uuid
from typing import Any

# 3rd party imports
import asyncpg
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

# local imports
from mailalias.config import BACKEND_DIR
from mailalias.models import Base
from tests.integration.conftest import _ensure_database

# The oldest revision the round trip goes back to (the schema before the operator pivot).
ROUND_TRIP_BASE = "0002"


def _alembic_config(url: str) -> Config:
    """Alembic config pointed at one database.

    Args:
        url: SQLAlchemy URL of the target database.
    Returns:
        The config.
    """
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = url
    return cfg


async def _scratch(migrated_db: str) -> tuple[str, Config]:
    """A scratch database next to the test database, migrated to head.

    Args:
        migrated_db: URL of the main test database (its server hosts the scratch one).
    Returns:
        (scratch URL, alembic config for it).
    """
    url = migrated_db.rsplit("/", 1)[0] + "/mailalias_migrations"
    await _ensure_database(url)
    cfg = _alembic_config(url)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    return url, cfg


async def test_migrations_round_trip(migrated_db: str) -> None:
    """Upgrade to head, downgrade to 0002 and upgrade again on a separate scratch database.

    Args:
        migrated_db: URL of the main test database.
    Returns:
        None.
    """
    _, cfg = await _scratch(migrated_db)
    await asyncio.to_thread(command.downgrade, cfg, ROUND_TRIP_BASE)
    await asyncio.to_thread(command.upgrade, cfg, "head")


async def test_default_inbox_backfill_flags_only_the_old_default(migrated_db: str) -> None:
    """0004 marks exactly each user's previous default recipient as a default inbox.

    Args:
        migrated_db: URL of the main test database.
    Returns:
        None.
    """
    url, cfg = await _scratch(migrated_db)
    await asyncio.to_thread(command.downgrade, cfg, "0003")
    conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
    users = [uuid.uuid4(), uuid.uuid4()]
    old_default, other, no_default = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    try:
        for index, user_id in enumerate(users):
            await conn.execute(
                "insert into users (id, username, email, email_hash, password_hash, role,"
                " totp_enabled, backup_codes_hash, banner_position, alias_format,"
                " strip_trackers, subdomain_catchall) values ($1, $2, 'e', $3, 'x', 'user',"
                " false, '[]', 'top', 'words', true, false)",
                user_id,
                f"backfill{index}",
                f"hash{index}",
            )
        for recipient_id, user_id in (
            (old_default, users[0]),
            (other, users[0]),
            (no_default, users[1]),
        ):
            await conn.execute(
                "insert into recipients (id, user_id, email, email_hash, pgp_protect_subject,"
                " consecutive_hard_bounces) values ($1, $2, 'e', $3, false, 0)",
                recipient_id,
                user_id,
                str(recipient_id),
            )
        await conn.execute(
            "update users set default_recipient_id = $1 where id = $2", old_default, users[0]
        )
        await asyncio.to_thread(command.upgrade, cfg, "0004")
        rows = await conn.fetch("select id, forward_by_default from recipients")
        assert {row["id"]: row["forward_by_default"] for row in rows} == {
            old_default: True,
            other: False,
            no_default: False,
        }
    finally:
        await conn.execute("delete from users where id = any($1::uuid[])", users)
        await conn.close()
    await asyncio.to_thread(command.upgrade, cfg, "head")


def _diff(connection: Connection) -> list[Any]:
    """Differences between the live schema and the ORM metadata.

    Args:
        connection: Sync connection to the migrated database.
    Returns:
        Alembic's diff list (empty when they match).
    """
    context = MigrationContext.configure(connection, opts={"compare_type": True})
    return compare_metadata(context, Base.metadata)


async def test_models_match_migrations(engine: AsyncEngine) -> None:
    """The migrated test database has exactly the tables, columns and indexes the models declare.

    Args:
        engine: Engine bound to the migrated test database.
    Returns:
        None.
    """
    async with engine.connect() as conn:
        diff = await conn.run_sync(_diff)
    assert diff == []
