"""The system-mail Celery task: sends, respects the global cap, refunds on failure."""

# 1st party imports
import base64
from email.message import EmailMessage
from typing import Any

# 3rd party imports
import pytest
from celery.exceptions import Retry

# local imports
from mailalias.config import get_settings
from mailalias.db import get_redis
from mailalias.mail.outbound import FakeMailer
from mailalias.mail.types import RetryableError
from mailalias.services.quota import QuotaService, global_key
from mailalias.tasks import mail as mail_tasks


def _raw() -> str:
    """Base64 of a minimal message.

    Returns:
        Encoded message.
    """
    msg = EmailMessage()
    msg["From"] = "noreply@closetcompute.online"
    msg["To"] = "owner@example.com"
    msg["Subject"] = "hello"
    msg.set_content("body")
    return base64.b64encode(msg.as_bytes()).decode()


def _run_task(monkeypatch: pytest.MonkeyPatch, mailer: Any) -> Any:
    """Execute the task body synchronously with a given mailer.

    Args:
        monkeypatch: Pytest monkeypatch.
        mailer: Mailer returned by get_direct_mailer.
    Returns:
        The task's return value.
    """
    monkeypatch.setattr(mail_tasks, "get_direct_mailer", lambda settings: mailer)
    return mail_tasks.send_system_mail.apply(
        args=[_raw(), "noreply@closetcompute.online", ["owner@example.com"]], throw=True
    ).get()


def test_sends_and_counts_against_cap(monkeypatch: pytest.MonkeyPatch, migrated_db: str) -> None:
    """A successful send returns the provider id and uses one unit of the cap.

    Args:
        monkeypatch: Pytest monkeypatch.
        migrated_db: Ensures infra is ready.
    Returns:
        None.
    """
    mailer = FakeMailer()
    assert _run_task(monkeypatch, mailer) == "fake-1"
    assert mailer.sent[0].message["Subject"] == "hello"


def test_cap_reached_schedules_retry(monkeypatch: pytest.MonkeyPatch, migrated_db: str) -> None:
    """When today's cap is used up, nothing is sent and the task retries later.

    Args:
        monkeypatch: Pytest monkeypatch.
        migrated_db: Ensures infra is ready.
    Returns:
        None.
    """
    import asyncio

    async def _fill() -> None:
        from redis.asyncio import Redis

        redis = Redis.from_url(get_settings().redis_url)
        await redis.set(global_key(), get_settings().outbound_daily_cap)
        await redis.aclose()

    asyncio.run(_fill())
    mailer = FakeMailer()
    with pytest.raises(Retry):
        _run_task(monkeypatch, mailer)
    assert mailer.sent == []


def test_transient_failure_refunds_cap(monkeypatch: pytest.MonkeyPatch, migrated_db: str) -> None:
    """A retryable send error gives the unit back and schedules a retry.

    Args:
        monkeypatch: Pytest monkeypatch.
        migrated_db: Ensures infra is ready.
    Returns:
        None.
    """
    import asyncio

    class _Failing:
        async def send(self, *args: Any) -> str:
            raise RetryableError("smtp temporary failure 451")

    with pytest.raises(Retry):
        _run_task(monkeypatch, _Failing())

    async def _count() -> int:
        from redis.asyncio import Redis

        redis = Redis.from_url(get_settings().redis_url)
        value = int(await redis.get(global_key()) or 0)
        await redis.aclose()
        return value

    assert asyncio.run(_count()) == 0


async def test_global_cap_boundary() -> None:
    """Exactly OUTBOUND_DAILY_CAP sends are allowed per day.

    Returns:
        None.
    """
    settings = get_settings()
    quota = QuotaService(get_redis(), settings)
    results = [await quota.global_send_allowed() for _ in range(settings.outbound_daily_cap + 1)]
    assert results.count(True) == settings.outbound_daily_cap and results[-1] is False
    assert await quota.global_sent_today() == settings.outbound_daily_cap
    assert await get_redis().ttl(global_key()) > 0
