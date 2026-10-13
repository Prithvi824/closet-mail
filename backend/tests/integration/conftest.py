"""Integration fixtures: a migrated test database and a rolled-back session per test."""

# 1st party imports
import asyncio
from collections.abc import AsyncIterator, Iterator

# 3rd party imports
import asyncpg
import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

# local imports
from mailalias.api.app import create_app
from mailalias.config import BACKEND_DIR, get_settings
from mailalias.db import get_redis, get_session
from mailalias.mail.outbound import FakeMailer, get_mailer
from mailalias.services import task_dispatch


async def _ensure_database(url: str) -> None:
    """Create the test database if it does not exist.

    Args:
        url: SQLAlchemy URL of the test database.
    Returns:
        None.
    """
    plain_url = url.replace("postgresql+asyncpg://", "postgresql://")
    server_url, db_name = plain_url.rsplit("/", 1)
    conn = await asyncpg.connect(f"{server_url}/postgres")
    try:
        exists = await conn.fetchval("select 1 from pg_database where datname = $1", db_name)
        if not exists:
            await conn.execute(f'create database "{db_name}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[str]:
    """Create (if needed) and migrate the test database to head.

    Returns:
        The test database URL.
    """
    url = get_settings().database_url
    asyncio.run(_ensure_database(url))
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")
    yield url


@pytest.fixture(scope="session")
async def engine(migrated_db: str) -> AsyncIterator[AsyncEngine]:
    """Async engine bound to the migrated test database.

    Args:
        migrated_db: Test database URL.
    Returns:
        An async iterator yielding the engine.
    """
    test_engine = create_async_engine(migrated_db)
    yield test_engine
    await test_engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Session inside an outer transaction that is rolled back after the test.

    Args:
        engine: Test engine.
    Returns:
        An async iterator yielding the session; commits become savepoints.
    """
    async with engine.connect() as conn:
        transaction = await conn.begin()
        test_session = AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield test_session
        finally:
            await test_session.close()
            await transaction.rollback()


@pytest.fixture(autouse=True)
async def clean_redis() -> AsyncIterator[None]:
    """Empty the test Redis database (db 15) before each test.

    Returns:
        An async iterator yielding once.
    """
    await get_redis().flushdb()
    yield


@pytest.fixture
def mailer() -> FakeMailer:
    """Fresh in-memory mailer capturing system mail.

    Returns:
        A FakeMailer.
    """
    return FakeMailer()


@pytest.fixture
def relaxed_rate_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Raise the auth rate limit so multi-step auth flows are not throttled.

    Args:
        monkeypatch: Pytest monkeypatch.
    Returns:
        None.
    """
    monkeypatch.setattr("mailalias.api.ratelimit.AUTH_LIMIT", 1000)


@pytest.fixture
def app(session: AsyncSession, mailer: FakeMailer) -> FastAPI:
    """Application using the rolled-back test session and the fake mailer.

    Args:
        session: Test session.
        mailer: Fake mailer.
    Returns:
        The FastAPI app.
    """
    application = create_app()

    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield session

    application.dependency_overrides[get_session] = _session_override
    application.dependency_overrides[get_mailer] = lambda: mailer
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client calling the app in-process, sending the CSRF header by default.

    Args:
        app: The application.
    Returns:
        An async iterator yielding the client.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", headers={"X-Requested-With": "mailalias"}
    ) as http_client:
        yield http_client


@pytest.fixture
def dispatched() -> Iterator[list[tuple[str, str]]]:
    """Capture background task dispatches (KV sync, releases) instead of sending them to Celery.

    Returns:
        An iterator yielding the list of (task name, object id) calls.
    """
    calls: list[tuple[str, str]] = []
    previous = task_dispatch.set_dispatcher(lambda task, object_id: calls.append((task, object_id)))
    yield calls
    task_dispatch.set_dispatcher(previous)
