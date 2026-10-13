"""Celery application, beat schedule and the async task runtime helper."""

# 1st party imports
import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

# 3rd party imports
from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# local imports
from mailalias.config import Settings, get_settings
from mailalias.integrations.cloudflare_api import CloudflareApi
from mailalias.integrations.cloudflare_kv import CloudflareKv
from mailalias.logging_setup import configure_logging

settings = get_settings()

celery_app = Celery(
    "mailalias",
    broker=settings.redis_url,
    include=[
        "mailalias.tasks.kv",
        "mailalias.tasks.mail",
        "mailalias.tasks.quarantine",
        "mailalias.tasks.maintenance",
        "mailalias.tasks.monitor",
    ],
)
celery_app.conf.update(
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "kv-reconcile": {"task": "kv.reconcile_all", "schedule": timedelta(minutes=15)},
        "retention": {"task": "maintenance.retention", "schedule": crontab(minute=7)},
        "monitor": {"task": "monitor.check", "schedule": timedelta(minutes=5)},
        # 02:00 Asia/Kolkata (UTC+05:30, no DST) = 20:30 UTC.
        "backup": {"task": "maintenance.backup", "schedule": crontab(hour=20, minute=30)},
    },
)


@setup_logging.connect
def _configure_worker_logging(**kwargs: Any) -> None:
    """Use the app's JSON logging (stdout + logs/worker/) instead of Celery's default.

    Args:
        kwargs: Signal arguments (unused).
    Returns:
        None.
    """
    configure_logging("worker")


@dataclass
class TaskContext:
    """Per-task resources created inside the task's own event loop."""

    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    redis: Redis
    cf_api: CloudflareApi

    @property
    def kv(self) -> CloudflareKv:
        """KV client for the configured namespace.

        Returns:
            A CloudflareKv.
        """
        return CloudflareKv(self.cf_api, self.settings.cf_kv_namespace_id)


@asynccontextmanager
async def task_context() -> AsyncIterator[TaskContext]:
    """Open fresh DB/Redis/HTTP clients bound to the current loop and close them after.

    Returns:
        An async context manager yielding a TaskContext.
    """
    task_settings = get_settings()
    # NullPool: each asyncio.run() gets a new loop, so pooled connections must not outlive it.
    engine = create_async_engine(task_settings.database_url, poolclass=NullPool)
    redis = Redis.from_url(task_settings.redis_url, decode_responses=True)
    cf_api = CloudflareApi(task_settings)
    try:
        yield TaskContext(
            settings=task_settings,
            session_factory=async_sessionmaker(engine, expire_on_commit=False),
            redis=redis,
            cf_api=cf_api,
        )
    finally:
        await cf_api.aclose()
        await redis.aclose()
        await engine.dispose()


def run_async[T](func: Callable[[TaskContext], Awaitable[T]]) -> T:
    """Run an async task body from a synchronous Celery task.

    Args:
        func: Coroutine function receiving a TaskContext.
    Returns:
        The coroutine's result.
    """

    async def _runner() -> T:
        async with task_context() as ctx:
            return await func(ctx)

    return asyncio.run(_runner())
