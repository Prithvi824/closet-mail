"""Record handled messages: the mail_log row, one delivery row per send, counters and usage."""

# 1st party imports
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

# 3rd party imports
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.mail.types import MailKind, Outcome
from mailalias.models import Alias, Contact, DeliveryLog, DeliveryStatus, MailLog, UsageDaily
from mailalias.security.crypto import lookup_hash

# Discard reasons that count as "blocked" on the alias (mail the owner chose not to receive).
BLOCKED_REASONS = frozenset({"alias_inactive"})

# usage_daily column bumped for each forward outcome (every forward also bumps "received").
FORWARD_OUTCOME_COLUMNS = {
    Outcome.DELIVERED: "forwards",
    Outcome.QUARANTINED: "quarantined",
    Outcome.BLOCKED: "blocked",
    Outcome.DISCARDED: "discarded",
}
# Reason on a forward delivered after release from quarantine (it was counted when it arrived).
RELEASED = "released"
USAGE_COLUMNS = ("received", "forwards", "quarantined", "blocked", "discarded", "replies", "bytes")


@dataclass(frozen=True)
class DeliveryRecord:
    """One completed send: the inbox (None for a reply) and the provider's message id."""

    recipient_id: uuid.UUID | None
    provider_id: str | None


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


def _usage_increments(
    kind: MailKind, outcome: Outcome, size_bytes: int, reason: str | None
) -> dict[str, int]:
    """usage_daily increments for one handled message (empty when it is not counted).

    Args:
        kind, outcome, reason: What happened (a release is not received a second time).
        size_bytes: Message size (counted only for delivered mail).
    Returns:
        Column name -> increment.
    """
    if kind == MailKind.FORWARD:
        increments = {} if reason == RELEASED else {"received": 1}
        column = FORWARD_OUTCOME_COLUMNS.get(outcome)
        if column:
            increments[column] = 1
        if outcome == Outcome.DELIVERED:
            increments["bytes"] = size_bytes
        return increments
    if kind == MailKind.REPLY and outcome == Outcome.DELIVERED:
        return {"replies": 1, "bytes": size_bytes}
    return {}


async def _bump_usage(
    db: AsyncSession, user_id: uuid.UUID, increments: dict[str, int], received_at: datetime
) -> None:
    """Upsert the usage_daily row for the day the message was received.

    Args:
        db: Session.
        user_id: Subdomain (user) the message belongs to.
        increments: Column name -> increment, from _usage_increments.
        received_at: When the edge accepted the message (its UTC date is the bucket).
    Returns:
        None.
    """
    values = {column: increments.get(column, 0) for column in USAGE_COLUMNS}
    statement = insert(UsageDaily).values(
        id=uuid.uuid4(), user_id=user_id, day=received_at.astimezone(UTC).date(), **values
    )
    set_: dict[str, object] = {
        column: getattr(UsageDaily, column) + statement.excluded[column] for column in USAGE_COLUMNS
    }
    set_["updated_at"] = datetime.now(UTC)
    statement = statement.on_conflict_do_update(constraint="uq_usage_daily_user_day", set_=set_)
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
    received_at: datetime | None = None,
    sender_address: str | None = None,
    deliveries: Sequence[DeliveryRecord] = (),
    count_usage: bool = True,
) -> MailLog:
    """Log one handled message with its deliveries; bump counters unless it is a redelivery.

    Args:
        db: Session (the caller commits).
        kind, outcome, reason, user_id, alias_id, contact_id, size_bytes, spam_score: Metadata.
        provider_id, deliveries: First send's id (legacy) and one record per send.
        received_at, sender_address, count_usage: Edge time, sender (domain kept), count it.
    Returns:
        The MailLog row.
    """
    now = datetime.now(UTC)
    received_at = received_at or now
    domain = None
    if sender_address and "@" in sender_address:
        domain = sender_address.rsplit("@", 1)[1].strip().lower() or None
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
        received_at=received_at,
        sender_domain_hash=lookup_hash(domain) if domain else None,
        sender_domain=domain,
    )
    db.add(entry)
    await db.flush()
    for delivery in deliveries:
        db.add(
            DeliveryLog(
                mail_log_id=entry.id,
                user_id=user_id,
                recipient_id=delivery.recipient_id,
                provider_id=delivery.provider_id,
                status=DeliveryStatus.SENT,
                status_at=now,
            )
        )
    if count_usage:
        await _bump_counters(
            db,
            kind=kind,
            outcome=outcome,
            reason=reason,
            alias_id=alias_id,
            contact_id=contact_id,
            now=now,
        )
        increments = _usage_increments(kind, outcome, size_bytes, reason)
        if user_id is not None and increments:
            await _bump_usage(db, user_id, increments, received_at)
    await db.flush()
    return entry
