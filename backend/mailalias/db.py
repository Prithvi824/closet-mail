"""Datastore handles: async SQLAlchemy engine/sessions and the shared async Redis client."""

# 1st party imports
from collections.abc import AsyncIterator
from functools import lru_cache

# 3rd party imports
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# local imports
from mailalias.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Create the process-wide async engine on first use.

    Returns:
        The shared AsyncEngine.
    """
    return create_async_engine(get_settings().database_url, pool_size=5, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create the session factory bound to the shared engine.

    Returns:
        An async_sessionmaker that does not expire objects on commit.
    """
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding one session per request.

    Returns:
        An async iterator yielding an AsyncSession that is closed afterwards.
    """
    async with get_session_factory()() as session:
        yield session


@lru_cache
def get_redis() -> "Redis":
    """Create the process-wide async Redis client (string responses).

    Returns:
        The shared Redis client.
    """
    return Redis.from_url(get_settings().redis_url, decode_responses=True)
