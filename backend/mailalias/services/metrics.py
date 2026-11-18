"""Metrics: how much mail arrived, from where, when and to whom. Read-only; decrypts only what
the operator is shown (sender domains and addresses, inbox addresses) and never logs them."""

# 1st party imports
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

# 3rd party imports
from redis.asyncio import Redis
from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.errors import ValidationFailed
from mailalias.config import Settings
from mailalias.mail.types import MailKind
from mailalias.models import (
    Alias,
    Contact,
    DeliveryLog,
    MailLog,
    Recipient,
    UsageDaily,
    User,
    UserRole,
)
from mailalias.schemas.metrics import (
    CountItem,
    DailyPoint,
    Destination,
    MailEvent,
    OutcomeTotals,
    OverviewResponse,
    SubdomainActivityResponse,
    SubdomainTotals,
)
from mailalias.services.quota import global_key, share_key, share_limit

MAX_DAYS = 90
TOP_N = 10
PAGE_SIZE = 50
COUNTERS = ("received", "forwards", "quarantined", "blocked", "discarded", "replies")


def _window(days: int) -> tuple[date, datetime]:
    """First day of the window and the matching start time.

    Args:
        days: Window length including today (1..90).
    Returns:
        (first UTC day, midnight UTC of that day). Raises ValidationFailed.
    """
    if not 1 <= days <= MAX_DAYS:
        raise ValidationFailed(f"days must be between 1 and {MAX_DAYS}")
    start = datetime.now(UTC).date() - timedelta(days=days - 1)
    return start, datetime(start.year, start.month, start.day, tzinfo=UTC)


def _totals(values: Sequence[Any] | None) -> OutcomeTotals:
    """Outcome totals from summed usage counters (in COUNTERS order).

    Args:
        values: Summed counters, or None when there was no usage.
    Returns:
        The totals.
    """
    received, forwards, quarantined, blocked, discarded, replies = (
        int(v or 0) for v in (values or (0,) * len(COUNTERS))
    )
    return OutcomeTotals(
        received=received,
        delivered=forwards,
        quarantined=quarantined,
        blocked=blocked,
        discarded=discarded,
        replies=replies,
    )


def _sums() -> list[Any]:
    """SUM() of every usage counter, in COUNTERS order.

    Returns:
        Column expressions.
    """
    return [func.sum(getattr(UsageDaily, column)) for column in COUNTERS]


async def _daily(
    db: AsyncSession, start: date, days: int, user_id: uuid.UUID | None
) -> list[DailyPoint]:
    """Zero-filled daily points, oldest first.

    Args:
        db: Session.
        start, days: Window.
        user_id: One subdomain, or None for all of them.
    Returns:
        One point per day.
    """
    query = select(UsageDaily.day, *_sums()).where(UsageDaily.day >= start).group_by(UsageDaily.day)
    if user_id is not None:
        query = query.where(UsageDaily.user_id == user_id)
    by_day = {row[0]: _totals(row[1:]) for row in (await db.execute(query)).all()}
    points = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        totals = by_day.get(day) or _totals(None)
        points.append(
            DailyPoint(
                day=day,
                received=totals.received,
                delivered=totals.delivered,
                replies=totals.replies,
            )
        )
    return points


async def _top_sender_domains(
    db: AsyncSession, since: datetime, user_id: uuid.UUID | None
) -> list[CountItem]:
    """The most common sender domains of received forwards, decrypted for display.

    Args:
        db: Session.
        since: Window start (received time).
        user_id: One subdomain, or None for all of them.
    Returns:
        Up to TOP_N items, most mail first.
    """
    query = (
        select(MailLog.sender_domain_hash, func.count().label("n"))
        .where(
            MailLog.kind == MailKind.FORWARD,
            MailLog.received_at >= since,
            MailLog.sender_domain_hash.is_not(None),
        )
        .group_by(MailLog.sender_domain_hash)
        .order_by(func.count().desc(), MailLog.sender_domain_hash)
        .limit(TOP_N)
    )
    if user_id is not None:
        query = query.where(MailLog.user_id == user_id)
    counts = (await db.execute(query)).all()
    if not counts:
        return []
    # Each value is encrypted with a fresh IV, so one row per hash is enough to read the name.
    names = dict(
        (
            await db.execute(
                select(MailLog.sender_domain_hash, MailLog.sender_domain)
                .where(MailLog.sender_domain_hash.in_([row[0] for row in counts]))
                .ext(distinct_on(MailLog.sender_domain_hash))
            )
        ).all()
    )
    return [CountItem(key=names.get(digest) or "unknown", count=int(n)) for digest, n in counts]


async def overview(
    db: AsyncSession, redis: Redis, settings: Settings, *, days: int
) -> OverviewResponse:
    """Every subdomain together: totals, a daily series, per-subdomain numbers, top domains.

    Args:
        db, redis, settings: Session, Redis (today's sends) and settings (caps).
        days: Window length including today (1..90).
    Returns:
        The overview.
    """
    start, since = _window(days)
    total_row = (await db.execute(select(*_sums()).where(UsageDaily.day >= start))).one()
    per_user = {
        row[0]: _totals(row[1:])
        for row in (
            await db.execute(
                select(UsageDaily.user_id, *_sums())
                .where(UsageDaily.day >= start)
                .group_by(UsageDaily.user_id)
            )
        ).all()
    }
    users = list(
        await db.scalars(select(User).order_by(User.role != UserRole.ADMIN, User.username))
    )
    sends = await redis.mget([share_key(user.id) for user in users]) if users else []
    per_subdomain = [
        SubdomainTotals(
            label=user.username,
            display_name=user.display_name,
            totals=per_user.get(user.id) or _totals(None),
            sends_today=int(sent or 0),
            send_share=share_limit(settings, user.limits),
        )
        for user, sent in zip(users, sends, strict=True)
        if user.retired_at is None or user.id in per_user
    ]
    return OverviewResponse(
        days=days,
        totals=_totals(total_row),
        daily=await _daily(db, start, days, None),
        per_subdomain=per_subdomain,
        top_sender_domains=await _top_sender_domains(db, since, None),
        sends_today=int(await redis.get(global_key()) or 0),
        send_cap=settings.outbound_daily_cap,
    )


async def _counts(db: AsyncSession, query: Select[str, int]) -> list[CountItem]:
    """Run a (key, count) query and wrap the rows.

    Args:
        db: Session.
        query: Selects (display key, count).
    Returns:
        Items.
    """
    return [CountItem(key=str(key), count=int(n)) for key, n in (await db.execute(query)).all()]


async def _top_senders(db: AsyncSession, user: User, since: datetime) -> list[CountItem]:
    """The subdomain's most frequent senders (full address, decrypted from the contact).

    Args:
        db: Session.
        user: Subdomain.
        since: Window start.
    Returns:
        Up to TOP_N items.
    """
    counts = (
        await db.execute(
            select(MailLog.contact_id, func.count())
            .where(
                MailLog.user_id == user.id,
                MailLog.kind == MailKind.FORWARD,
                MailLog.received_at >= since,
                MailLog.contact_id.is_not(None),
            )
            .group_by(MailLog.contact_id)
            .order_by(func.count().desc(), MailLog.contact_id)
            .limit(TOP_N)
        )
    ).all()
    contacts = {
        contact.id: contact.sender_email
        for contact in await db.scalars(
            select(Contact).where(Contact.id.in_([row[0] for row in counts]))
        )
    }
    return [
        CountItem(key=(contacts.get(cid) if cid else None) or "unknown", count=int(n))
        for cid, n in counts
    ]


async def _per_inbox(db: AsyncSession, user: User, since: datetime) -> list[CountItem]:
    """Copies delivered to each of the subdomain's inboxes.

    Args:
        db: Session.
        user: Subdomain.
        since: Window start.
    Returns:
        Up to TOP_N items.
    """
    counts = (
        await db.execute(
            select(DeliveryLog.recipient_id, func.count())
            .where(
                DeliveryLog.user_id == user.id,
                DeliveryLog.created_at >= since,
                DeliveryLog.recipient_id.is_not(None),
            )
            .group_by(DeliveryLog.recipient_id)
            .order_by(func.count().desc(), DeliveryLog.recipient_id)
            .limit(TOP_N)
        )
    ).all()
    emails = {
        recipient.id: recipient.email
        for recipient in await db.scalars(
            select(Recipient).where(Recipient.id.in_([row[0] for row in counts]))
        )
    }
    return [
        CountItem(key=(emails.get(rid) if rid else None) or "removed inbox", count=int(n))
        for rid, n in counts
    ]


async def _recent(
    db: AsyncSession, user: User, since: datetime, page: int
) -> tuple[list[MailEvent], bool]:
    """One page of the subdomain's mail, newest first, in two queries (rows, then deliveries).

    Args:
        db: Session.
        user: Subdomain.
        since: Window start.
        page: 1-based page.
    Returns:
        (events, whether another page exists).
    """
    rows = (
        await db.execute(
            select(MailLog, Alias.address, Contact)
            .outerjoin(Alias, Alias.id == MailLog.alias_id)
            .outerjoin(Contact, Contact.id == MailLog.contact_id)
            .where(MailLog.user_id == user.id, MailLog.received_at >= since)
            .order_by(MailLog.received_at.desc(), MailLog.created_at.desc(), MailLog.id)
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE + 1)
        )
    ).all()
    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    destinations: dict[uuid.UUID, list[Destination]] = {}
    if rows:
        deliveries = await db.execute(
            select(DeliveryLog, Recipient.email)
            .outerjoin(Recipient, Recipient.id == DeliveryLog.recipient_id)
            .where(DeliveryLog.mail_log_id.in_([row[0].id for row in rows]))
            .order_by(DeliveryLog.created_at)
        )
        for delivery, email in deliveries.all():
            destinations.setdefault(delivery.mail_log_id, []).append(
                Destination(inbox=email, status=delivery.status)
            )
    events = [
        MailEvent(
            id=log.id,
            received_at=log.received_at or log.created_at,
            kind=log.kind,
            outcome=log.outcome,
            reason=log.reason,
            alias_address=address,
            sender=contact.sender_email if contact is not None else None,
            sender_domain=log.sender_domain,
            destinations=destinations.get(log.id, []),
            spam_score=log.spam_score,
            size_bytes=log.size_bytes,
        )
        for log, address, contact in rows
    ]
    return events, has_more


async def subdomain_activity(
    db: AsyncSession, user: User, *, days: int, page: int
) -> SubdomainActivityResponse:
    """One subdomain: totals, daily series, top senders/domains/aliases/inboxes, recent mail.

    Args:
        db: Session.
        user: Subdomain.
        days, page: Window length (1..90) and 1-based page of recent mail.
    Returns:
        The activity.
    """
    start, since = _window(days)
    total_row = (
        await db.execute(
            select(*_sums()).where(UsageDaily.user_id == user.id, UsageDaily.day >= start)
        )
    ).one()
    per_alias = await _counts(
        db,
        select(Alias.address, func.count())
        .join(MailLog, MailLog.alias_id == Alias.id)
        .where(
            MailLog.user_id == user.id,
            MailLog.kind == MailKind.FORWARD,
            MailLog.received_at >= since,
        )
        .group_by(Alias.address)
        .order_by(func.count().desc(), Alias.address)
        .limit(TOP_N),
    )
    recent, has_more = await _recent(db, user, since, page)
    return SubdomainActivityResponse(
        days=days,
        totals=_totals(total_row),
        daily=await _daily(db, start, days, user.id),
        top_sender_domains=await _top_sender_domains(db, since, user.id),
        top_senders=await _top_senders(db, user, since),
        per_alias=per_alias,
        per_inbox=await _per_inbox(db, user, since),
        recent=recent,
        page=page,
        has_more=has_more,
    )
