"""Migrations round-trip on a scratch database and match the ORM models."""

# 1st party imports
import asyncio
from typing import Any

# 3rd party imports
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


async def test_migrations_round_trip(migrated_db: str) -> None:
    """Upgrade to head, downgrade to 0002 and upgrade again on a separate scratch database.

    Args:
        migrated_db: URL of the main test database (its server hosts the scratch one).
    Returns:
        None.
    """
    url = migrated_db.rsplit("/", 1)[0] + "/mailalias_migrations"
    await _ensure_database(url)
    cfg = _alembic_config(url)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    await asyncio.to_thread(command.downgrade, cfg, ROUND_TRIP_BASE)
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
