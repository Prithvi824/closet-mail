"""Celery tasks that publish alias/token/subdomain state to Workers KV."""

# 1st party imports
import logging
import uuid
from typing import Any

# local imports
from mailalias.mail.types import RetryableError
from mailalias.services import kv_sync
from mailalias.tasks.celery_app import TaskContext, celery_app, run_async

logger = logging.getLogger(__name__)

RETRY_OPTIONS: dict[str, Any] = {
    "autoretry_for": (RetryableError,),
    "retry_backoff": 10,
    "retry_backoff_max": 600,
    "max_retries": 8,
}


@celery_app.task(name="kv.sync_alias", **RETRY_OPTIONS)
def sync_alias(alias_id: str) -> None:
    """Publish one alias's state.

    Args:
        alias_id: Alias id.
    Returns:
        None.
    """

    async def _run(ctx: TaskContext) -> None:
        async with ctx.session_factory() as db:
            await kv_sync.sync_alias(db, ctx.kv, uuid.UUID(alias_id))

    run_async(_run)


@celery_app.task(name="kv.sync_contact", **RETRY_OPTIONS)
def sync_contact(contact_id: str) -> None:
    """Publish one reply token.

    Args:
        contact_id: Contact id.
    Returns:
        None.
    """

    async def _run(ctx: TaskContext) -> None:
        async with ctx.session_factory() as db:
            await kv_sync.sync_contact(db, ctx.kv, uuid.UUID(contact_id))

    run_async(_run)


@celery_app.task(name="kv.sync_subdomain", **RETRY_OPTIONS)
def sync_subdomain(user_id: str) -> None:
    """Publish a user's subdomain catch-all flag.

    Args:
        user_id: User id.
    Returns:
        None.
    """

    async def _run(ctx: TaskContext) -> None:
        async with ctx.session_factory() as db:
            await kv_sync.sync_subdomain(db, ctx.kv, uuid.UUID(user_id))

    run_async(_run)


@celery_app.task(name="kv.reconcile_all", **RETRY_OPTIONS)
def reconcile_all() -> dict[str, Any]:
    """Repair KV drift (deletes unknown keys only in production).

    Returns:
        The reconcile summary.
    """

    async def _run(ctx: TaskContext) -> dict[str, Any]:
        async with ctx.session_factory() as db:
            summary = await kv_sync.reconcile(
                db, ctx.kv, ctx.redis, delete_extra=ctx.settings.is_prod
            )
        logger.info("kv reconcile", extra=summary)
        return summary

    return run_async(_run)
