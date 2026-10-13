"""Per-user and global send quotas, and mail log counters/usage."""

# 1st party imports
import uuid
from datetime import UTC, datetime

# 3rd party imports
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.config import get_settings
from mailalias.db import get_redis
from mailalias.mail.types import MailKind, Outcome
from mailalias.models import Alias, Contact, MailLog, UsageDaily, User
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
    logs = (await session.scalars(select(MailLog).where(MailLog.alias_id == alias.id))).all()
    assert len(logs) == 3


async def test_record_blocked_and_inactive_count_as_blocked(
    session: AsyncSession, dispatched: list[tuple[str, str]]
) -> None:
    """BLOCKED and inactive-alias discards bump blocked_count; no usage is recorded."""
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
    usage = await session.scalar(select(UsageDaily).where(UsageDaily.user_id == user.id))
    assert usage is None
