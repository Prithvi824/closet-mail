"""Per-user and global send quotas, and mail log counters/usage."""

# 1st party imports
import uuid
from datetime import UTC, datetime, timedelta

# 3rd party imports
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.config import get_settings
from mailalias.db import get_redis
from mailalias.mail.types import MailKind, Outcome
from mailalias.models import (
    Alias,
    Contact,
    DeliveryLog,
    DeliveryStatus,
    MailLog,
    Recipient,
    UsageDaily,
    User,
)
from mailalias.security.crypto import lookup_hash
from mailalias.services import mail_log
from mailalias.services.aliases import AliasService
from mailalias.services.contacts import ContactService
from mailalias.services.quota import (
    DAY_TTL_SECONDS,
    HOUR_TTL_SECONDS,
    QuotaService,
    global_key,
    user_key,
)
from mailalias.services.users import UserService
from tests.integration.harness import default_inbox


def _quota() -> QuotaService:
    """Quota service on the test Redis.

    Returns:
        The service.
    """
    return QuotaService(get_redis(), get_settings())


def test_key_formats() -> None:
    """Forward counters are hourly, reply counters daily, global daily."""
    user_id = uuid.UUID(int=1)
    now = datetime(2026, 10, 12, 7, 30, tzinfo=UTC)
    assert user_key(user_id, "forward", now) == f"q:fwd:{user_id}:2026101207"
    assert user_key(user_id, "reply", now) == f"q:rep:{user_id}:20261012"
    assert global_key(now) == "q:global:20261012"


async def test_forward_quota_boundary_and_ttl() -> None:
    """Exactly `limit` units pass; the next is refused without changing the counter."""
    quota, user_id = _quota(), uuid.uuid4()
    limits = {"forwards_per_hour": 3}
    results = [await quota.check_and_consume(user_id, "forward", limits=limits) for _ in range(4)]
    assert results == [True, True, True, False]
    key = user_key(user_id, "forward")
    assert int(await get_redis().get(key) or 0) == 3
    assert 0 < await get_redis().ttl(key) <= HOUR_TTL_SECONDS


async def test_reply_quota_cost_and_refund() -> None:
    """Multi-unit costs respect the limit; refunds give units back."""
    quota, user_id = _quota(), uuid.uuid4()
    limits = {"replies_per_day": 2}
    assert not await quota.check_and_consume(user_id, "reply", 3, limits=limits)
    assert await quota.check_and_consume(user_id, "reply", 2, limits=limits)
    assert not await quota.check_and_consume(user_id, "reply", limits=limits)
    await quota.refund_user(user_id, "reply")
    assert await quota.check_and_consume(user_id, "reply", limits=limits)
    assert 0 < await get_redis().ttl(user_key(user_id, "reply")) <= DAY_TTL_SECONDS


def test_limit_override_falls_back_on_bad_values() -> None:
    """Non-integer or negative overrides are ignored."""
    quota, settings = _quota(), get_settings()
    assert quota.user_limit("forward") == settings.user_forwards_per_hour
    assert (
        quota.user_limit("forward", {"forwards_per_hour": "9"}) == settings.user_forwards_per_hour
    )
    assert quota.user_limit("reply", {"replies_per_day": -1}) == settings.user_replies_per_day
    assert quota.user_limit("reply", {"replies_per_day": 0}) == 0


async def test_global_cap_ttl() -> None:
    """The global counter expires."""
    assert await _quota().global_send_allowed()
    assert 0 < await get_redis().ttl(global_key()) <= DAY_TTL_SECONDS


async def _setup(session: AsyncSession) -> tuple[User, Alias, Contact]:
    """User with an alias and one contact.

    Args:
        session: Test session.
    Returns:
        (user, alias, contact).
    """
    user = await UserService(session).create_user("olga", "olga@example.com", "x" * 12)
    alias = await AliasService(session, get_settings()).create(user)
    contact = await ContactService(session).get_or_create(alias, "a@example.org", None)
    return user, alias, contact


async def test_record_delivered_forward_updates_counters_and_usage(
    session: AsyncSession, dispatched: list[tuple[str, str]]
) -> None:
    """Two forwards and a reply aggregate into one usage_daily row."""
    user, alias, contact = await _setup(session)
    for kind, size in ((MailKind.FORWARD, 100), (MailKind.FORWARD, 50), (MailKind.REPLY, 7)):
        await mail_log.record(
            session,
            kind=kind,
            outcome=Outcome.DELIVERED,
            user_id=user.id,
            alias_id=alias.id,
            contact_id=contact.id,
            size_bytes=size,
            provider_id="resend-id",
        )
    await session.refresh(alias)
    await session.refresh(contact)
    assert (alias.forwarded_count, alias.replied_count, alias.blocked_count) == (2, 1, 0)
    assert alias.last_used_at is not None
    assert (contact.forwarded_count, contact.replied_count) == (2, 1)
    usage = (await session.scalars(select(UsageDaily).where(UsageDaily.user_id == user.id))).one()
    assert (usage.forwards, usage.replies, usage.bytes) == (2, 1, 157)
    assert usage.received == 2
    logs = (await session.scalars(select(MailLog).where(MailLog.alias_id == alias.id))).all()
    assert len(logs) == 3


async def test_record_blocked_and_inactive_count_as_blocked(
    session: AsyncSession, dispatched: list[tuple[str, str]]
) -> None:
    """BLOCKED and inactive-alias discards bump blocked_count; usage counts them by outcome."""
    user, alias, contact = await _setup(session)
    await mail_log.record(
        session,
        kind=MailKind.FORWARD,
        outcome=Outcome.BLOCKED,
        user_id=user.id,
        alias_id=alias.id,
        contact_id=contact.id,
    )
    await mail_log.record(
        session,
        kind=MailKind.FORWARD,
        outcome=Outcome.DISCARDED,
        reason="alias_inactive",
        user_id=user.id,
        alias_id=alias.id,
    )
    await mail_log.record(
        session, kind=MailKind.FORWARD, outcome=Outcome.DISCARDED, reason="quota", user_id=user.id
    )
    await session.refresh(alias)
    await session.refresh(contact)
    assert (alias.blocked_count, alias.forwarded_count) == (2, 0)
    assert contact.forwarded_count == 0
    usage = (await session.scalars(select(UsageDaily).where(UsageDaily.user_id == user.id))).one()
    assert (usage.received, usage.blocked, usage.discarded) == (3, 1, 2)
    assert (usage.forwards, usage.quarantined, usage.bytes) == (0, 0, 0)


async def test_record_writes_one_delivery_row_per_inbox(
    session: AsyncSession, dispatched: list[tuple[str, str]]
) -> None:
    """A forward delivered to two inboxes logs two delivery rows and counts as one received."""
    user, alias, contact = await _setup(session)
    first = await default_inbox(session, user)
    second = Recipient(user_id=user.id, email="o2@example.com", email_hash=lookup_hash("o2@x"))
    session.add(second)
    await session.flush()
    entry = await mail_log.record(
        session,
        kind=MailKind.FORWARD,
        outcome=Outcome.DELIVERED,
        user_id=user.id,
        alias_id=alias.id,
        contact_id=contact.id,
        size_bytes=10,
        provider_id="re_1",
        deliveries=[
            mail_log.DeliveryRecord(first.id, "re_1"),
            mail_log.DeliveryRecord(second.id, "re_2"),
        ],
    )
    rows = (
        await session.scalars(select(DeliveryLog).where(DeliveryLog.mail_log_id == entry.id))
    ).all()
    assert {(r.recipient_id, r.provider_id) for r in rows} == {
        (first.id, "re_1"),
        (second.id, "re_2"),
    }
    assert all(r.status is DeliveryStatus.SENT and r.user_id == user.id for r in rows)
    usage = (await session.scalars(select(UsageDaily).where(UsageDaily.user_id == user.id))).one()
    assert (usage.received, usage.forwards, usage.bytes) == (1, 1, 10)


async def test_record_without_usage_leaves_counters_alone(
    session: AsyncSession, dispatched: list[tuple[str, str]]
) -> None:
    """count_usage=False (a redelivered message) logs the row but bumps no counter."""
    user, alias, contact = await _setup(session)
    await mail_log.record(
        session,
        kind=MailKind.FORWARD,
        outcome=Outcome.DELIVERED,
        user_id=user.id,
        alias_id=alias.id,
        contact_id=contact.id,
        size_bytes=10,
        count_usage=False,
    )
    await session.refresh(alias)
    await session.refresh(contact)
    assert (alias.forwarded_count, contact.forwarded_count) == (0, 0)
    assert await session.scalar(select(UsageDaily).where(UsageDaily.user_id == user.id)) is None
    assert await session.scalar(select(MailLog).where(MailLog.alias_id == alias.id)) is not None


async def test_record_stores_sender_domain_hashed_and_encrypted(
    session: AsyncSession, dispatched: list[tuple[str, str]]
) -> None:
    """The sender's domain is kept as a lookup hash plus an encrypted value, never the address."""
    user, alias, _ = await _setup(session)
    entry = await mail_log.record(
        session,
        kind=MailKind.FORWARD,
        outcome=Outcome.DELIVERED,
        user_id=user.id,
        alias_id=alias.id,
        sender_address="a@Example.com",
    )
    assert entry.sender_domain_hash == lookup_hash("example.com")
    assert entry.sender_domain == "example.com"
    assert entry.received_at is not None


async def test_record_buckets_usage_by_received_day(
    session: AsyncSession, dispatched: list[tuple[str, str]]
) -> None:
    """Mail the edge accepted on an earlier day counts toward that day, not processing day."""
    user, alias, _ = await _setup(session)
    received = datetime.now(UTC) - timedelta(days=3)
    entry = await mail_log.record(
        session,
        kind=MailKind.FORWARD,
        outcome=Outcome.QUARANTINED,
        user_id=user.id,
        alias_id=alias.id,
        received_at=received,
    )
    assert entry.received_at == received
    usage = (await session.scalars(select(UsageDaily).where(UsageDaily.user_id == user.id))).one()
    assert usage.day == received.date()
    assert (usage.received, usage.quarantined) == (1, 1)
