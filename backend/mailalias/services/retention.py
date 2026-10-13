"""Data retention: expired quarantine, old logs and failures, stale invite and verify tokens."""

# 1st party imports
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

# 3rd party imports
from sqlalchemy import Executable, delete, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.integrations.r2 import ObjectStore
from mailalias.models import FailedDelivery, Invite, MailLog, QuarantineItem, Recipient
from mailalias.services.recipients import VERIFY_TTL

logger = logging.getLogger(__name__)

MAIL_LOG_DAYS = 30
FAILED_DELIVERY_DAYS = 90
QUARANTINE_BATCH = 200


@dataclass(frozen=True)
class RetentionResult:
    """Rows removed (or tokens cleared) by one run."""

    quarantine: int
    mail_log: int
    failed_deliveries: int
    invites: int
    verify_tokens: int


async def _affected(db: AsyncSession, statement: Executable) -> int:
    """Run a bulk DELETE/UPDATE and return the affected row count.

    Args:
        db: Session.
        statement: Bulk statement.
    Returns:
        Rows affected.
    """
    result = cast(CursorResult[Any], await db.execute(statement))
    return result.rowcount or 0


async def purge_quarantine(db: AsyncSession, storage: ObjectStore, now: datetime) -> int:
    """Delete expired or released quarantine rows and their encrypted R2 copies.

    Args:
        db: Session (the caller commits).
        storage: Object store.
        now: Current time.
    Returns:
        Rows deleted (at most QUARANTINE_BATCH per run; the next run continues).
    """
    items = list(
        await db.scalars(
            select(QuarantineItem)
            .where(or_(QuarantineItem.expires_at <= now, QuarantineItem.released_at.is_not(None)))
            .limit(QUARANTINE_BATCH)
        )
    )
    for item in items:
        await storage.delete(item.r2_key)  # also covered by the 8-day R2 lifecycle rule
        await db.delete(item)
    return len(items)


async def run_retention(
    db: AsyncSession, storage: ObjectStore, now: datetime | None = None
) -> RetentionResult:
    """Apply every retention rule once.

    Args:
        db: Session (the caller commits).
        storage: Object store for quarantined messages.
        now: Override for tests.
    Returns:
        Counts per rule.
    """
    now = now or datetime.now(UTC)
    quarantine = await purge_quarantine(db, storage, now)
    mail_log = await _affected(
        db, delete(MailLog).where(MailLog.created_at < now - timedelta(days=MAIL_LOG_DAYS))
    )
    failures = await _affected(
        db,
        delete(FailedDelivery).where(
            FailedDelivery.created_at < now - timedelta(days=FAILED_DELIVERY_DAYS)
        ),
    )
    invites = await _affected(
        db, delete(Invite).where(Invite.expires_at < now, Invite.used_at.is_(None))
    )
    tokens = await _affected(
        db,
        update(Recipient)
        .where(
            Recipient.verify_token_hash.is_not(None),
            Recipient.verify_sent_at < now - VERIFY_TTL,
        )
        .values(verify_token_hash=None),
    )
    result = RetentionResult(
        quarantine=quarantine,
        mail_log=mail_log,
        failed_deliveries=failures,
        invites=invites,
        verify_tokens=tokens,
    )
    logger.info("retention", extra=vars(result))
    return result
