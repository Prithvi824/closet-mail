"""Celery tasks for housekeeping: hourly retention and the nightly encrypted backup."""

# 1st party imports
from dataclasses import asdict
from typing import Any

# local imports
from mailalias.integrations.r2 import R2Storage
from mailalias.services.backup import run_backup
from mailalias.services.retention import run_retention
from mailalias.tasks.celery_app import TaskContext, celery_app, run_async
from mailalias.tasks.kv import RETRY_OPTIONS


@celery_app.task(name="maintenance.retention")
def retention() -> dict[str, Any]:
    """Purge expired quarantine, old logs/failures and stale tokens.

    Returns:
        Counts per rule.
    """

    async def _run(ctx: TaskContext) -> dict[str, Any]:
        """Run retention in one transaction.

        Args:
            ctx: Task resources.
        Returns:
            Counts per rule.
        """
        async with ctx.session_factory() as db:
            result = await run_retention(db, R2Storage(ctx.settings))
            await db.commit()
        return asdict(result)

    return run_async(_run)


@celery_app.task(name="maintenance.backup", **RETRY_OPTIONS)
def backup() -> str:
    """Dump, encrypt and upload the database to R2 backups/.

    Returns:
        The object key.
    """

    async def _run(ctx: TaskContext) -> str:
        """Run the backup.

        Args:
            ctx: Task resources.
        Returns:
            The object key.
        """
        return await run_backup(ctx.settings, R2Storage(ctx.settings))

    return run_async(_run)
