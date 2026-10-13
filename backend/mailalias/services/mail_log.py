"""Record handled messages: the mail_log row plus alias/contact counters and daily usage."""

# 1st party imports
import uuid
from datetime import UTC, datetime

# 3rd party imports
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.mail.types import MailKind, Outcome
from mailalias.models import Alias, Contact, MailLog, UsageDaily

# Discard reasons that count as "blocked" on the alias (mail the owner chose not to receive).
BLOCKED_REASONS = frozenset({"alias_inactive"})


async def _bump_counters(
    db: AsyncSession,
    *,
    kind: MailKind,
    outcome: Outcome,
    reason: str | None,
    alias_id: uuid.UUID | None,
    contact_id: uuid.UUID | None,
    now: datetime,
) -> None:
    """Increment alias/contact counters for one outcome (atomic SQL updates).

    Args:
        db: Session.
        kind: Mail kind.
        outcome: Outcome.
        reason: Outcome reason.
        alias_id: Alias, if known.
        contact_id: Contact, if known.
        now: Timestamp.
    Returns:
        None.
    """
    delivered = outcome == Outcome.DELIVERED
    if alias_id is not None:
        values: dict[str, object] = {}
        if delivered and kind == MailKind.FORWARD:
            values = {"forwarded_count": Alias.forwarded_count + 1, "last_used_at": now}
        elif delivered and kind == MailKind.REPLY:
            values = {"replied_count": Alias.replied_count + 1, "last_used_at": now}
        elif outcome == Outcome.BLOCKED or reason in BLOCKED_REASONS:
            values = {"blocked_count": Alias.blocked_count + 1}
        if values:
            await db.execute(update(Alias).where(Alias.id == alias_id).values(**values))
    if contact_id is not None and delivered:
        column = "forwarded_count" if kind == MailKind.FORWARD else "replied_count"
        await db.execute(
            update(Contact)
            .where(Contact.id == contact_id)
            .values({column: getattr(Contact, column) + 1, "last_seen_at": now})
        )


async def _bump_usage(
    db: AsyncSession, user_id: uuid.UUID, kind: MailKind, size_bytes: int, now: datetime
) -> None:
    """Upsert today's usage_daily row for a delivered forward or reply.

    Args:
        db: Session.
        user_id: User.
        kind: FORWARD or REPLY.
        size_bytes: Message size.
        now: Timestamp (its UTC date is the bucket).
    Returns:
        None.
    """
    forwards, replies = (1, 0) if kind == MailKind.FORWARD else (0, 1)
    statement = insert(UsageDaily).values(
        id=uuid.uuid4(),
        user_id=user_id,
        day=now.date(),
        forwards=forwards,
        replies=replies,
        bytes=size_bytes,
    )
    statement = statement.on_conflict_do_update(
        constraint="uq_usage_daily_user_day",
        set_={
            "forwards": UsageDaily.forwards + statement.excluded.forwards,
            "replies": UsageDaily.replies + statement.excluded.replies,
            "bytes": UsageDaily.bytes + statement.excluded.bytes,
            "updated_at": now,
        },
    )
    await db.execute(statement)


async def record(
    db: AsyncSession,
    *,
    kind: MailKind,
    outcome: Outcome,
    user_id: uuid.UUID | None = None,
    alias_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    reason: str | None = None,
    size_bytes: int = 0,
    spam_score: float | None = None,
    provider_id: str | None = None,
) -> MailLog:
    """Log one handled message and update counters (no subjects or addresses are stored).

    Args:
        db: Session (the caller commits).
        kind, outcome, reason: What happened.
        user_id, alias_id, contact_id, size_bytes, spam_score, provider_id: Metadata.
    Returns:
        The MailLog row.
    """
    now = datetime.now(UTC)
    entry = MailLog(
        user_id=user_id,
        alias_id=alias_id,
        contact_id=contact_id,
        kind=kind,
        outcome=outcome,
        reason=reason,
        size_bytes=size_bytes,
        spam_score=spam_score,
        provider_id=provider_id,
    )
    db.add(entry)
    await _bump_counters(
        db,
        kind=kind,
        outcome=outcome,
        reason=reason,
        alias_id=alias_id,
        contact_id=contact_id,
        now=now,
    )
    if (
        user_id is not None
        and outcome == Outcome.DELIVERED
        and kind
        in (
            MailKind.FORWARD,
            MailKind.REPLY,
        )
    ):
        await _bump_usage(db, user_id, kind, size_bytes, now)
    await db.flush()
    return entry
