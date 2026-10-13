"""Alembic environment: async engine, URL from Settings, metadata from mailalias.models."""

# 1st party imports
import asyncio
from logging.config import fileConfig
from typing import Any

# 3rd party imports
from alembic import context
from alembic.autogenerate.api import AutogenContext
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

# local imports
from mailalias.config import get_settings
from mailalias.models import Base
from mailalias.security.crypto import EncryptedString

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def render_item(type_: str, obj: Any, autogen_context: AutogenContext) -> str | bool:
    """Render app-only column types as their plain database type in migration scripts.

    Args:
        type_: Kind of object being rendered ("type", "column", ...).
        obj: The object itself.
        autogen_context: Alembic autogenerate context.
    Returns:
        Source text to use, or False for Alembic's default rendering.
    """
    if type_ == "type" and isinstance(obj, EncryptedString):
        return "sa.Text()"
    return False


def _configure(**kwargs: Any) -> None:
    """Apply the options shared by offline and online runs.

    Args:
        kwargs: Mode-specific options for context.configure.
    Returns:
        None.
    """
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        render_item=render_item,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a database connection.

    Returns:
        None.
    """
    _configure(
        url=get_settings().database_url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations on a live (sync-adapted) connection.

    Args:
        connection: Connection from the async engine.
    Returns:
        None.
    """
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Open an async engine for DATABASE_URL and run migrations through it.

    Returns:
        None.
    """
    url = config.attributes.get("database_url") or get_settings().database_url
    engine = create_async_engine(url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
