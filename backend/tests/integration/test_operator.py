"""Operator console API: access control, health and DLQ recovery."""

# 1st party imports
import json
from datetime import UTC, datetime
from typing import Any

# 3rd party imports
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.deps import get_queue_admin
from mailalias.config import get_settings
from mailalias.db import get_redis
from mailalias.mail.outbound import FakeMailer
from mailalias.mail.processor import HEARTBEAT_KEY
from mailalias.models import FailureKind, User, UserRole
from mailalias.security.sessions import SESSION_COOKIE, SessionStore
from mailalias.services.failed_deliveries import FailedDeliveryService
from mailalias.services.quota import global_key
from mailalias.services.system_mail import SystemMailService
from mailalias.services.users import UserService
from tests.integration.harness import FakeQueues

pytestmark = pytest.mark.usefixtures("dispatched", "relaxed_rate_limits")
PASSWORD = "admin-password-1"


def _job(r2_key: str) -> dict[str, Any]:
    """A v1 inbound job body.

    Args:
        r2_key: Raw message key.
    Returns:
        The job.
    """
    return {
        "v": 1,
        "r2Key": r2_key,
        "mailFrom": "a@example.org",
        "rcptTo": "x@closetcompute.online",
        "rawSize": 10,
        "receivedAt": "2026-10-12T06:00:00Z",
    }


@pytest.fixture
def queues(app: FastAPI) -> FakeQueues:
    """Fake queue client injected into the app.

    Args:
        app: Application.
    Returns:
        The fake.
    """
    fake = FakeQueues()
    app.dependency_overrides[get_queue_admin] = lambda: fake
    return fake


async def _users(session: AsyncSession) -> tuple[User, User]:
    """An admin and a normal user.

    Args:
        session: Test session.
    Returns:
        (admin, user).
    """
    service = UserService(session)
    admin = await service.create_user("boss", "boss@example.com", PASSWORD, UserRole.ADMIN)
    user = await service.create_user("pia", "pia@example.com", PASSWORD)
    await session.commit()
    return admin, user


async def _login(client: httpx.AsyncClient, username: str) -> None:
    """Log in.

    Args:
        client: Client.
        username: Username.
    Returns:
        None.
    """
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200


@pytest.mark.usefixtures("queues")
async def test_non_operator_session_is_refused(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Every operator endpoint refuses a non-operator, even with a session from before."""
    _, user = await _users(session)
    sid = await SessionStore(get_redis()).create(user.id, mfa_passed=True)
    client.cookies.set(SESSION_COOKIE, sid)
    for method, url in (
        ("GET", "/api/v1/operator/subdomains"),
        ("GET", "/api/v1/operator/health"),
        ("GET", "/api/v1/operator/dlq"),
        ("POST", "/api/v1/operator/dlq/retry"),
    ):
        response = await client.request(method, url, json={} if method == "POST" else None)
        assert response.status_code == 401, url


async def test_health_numbers(
    client: httpx.AsyncClient, session: AsyncSession, queues: FakeQueues
) -> None:
    """Heartbeat age, backlogs, today's sends, 7-day failures and reconcile state."""
    _, user = await _users(session)
    settings = get_settings()
    queues.backlog = {settings.cf_queue_id_inbound: 3, settings.cf_queue_id_dlq: 1}
    redis = get_redis()
    await redis.set(HEARTBEAT_KEY, datetime.now(UTC).isoformat())
    await redis.set(global_key(), 12)
    await redis.set(
        "kv:last_reconcile", json.dumps({"at": "2026-10-12T06:00:00+00:00", "missing": 0})
    )
    failed = FailedDeliveryService(session, SystemMailService(FakeMailer(), settings))
    await failed.record(FailureKind.HARD, user_id=user.id)
    await failed.record(FailureKind.COMPLAINT, user_id=user.id)
    await session.commit()
    await _login(client, "boss")
    body = (await client.get("/api/v1/operator/health")).json()
    assert 0 <= body["heartbeat_age_seconds"] < 60
    assert (body["inbound_backlog"], body["dlq_backlog"]) == (3, 1)
    assert (body["sends_today"], body["send_cap"]) == (12, settings.outbound_daily_cap)
    assert (body["hard_bounces_7d"], body["complaints_7d"]) == (1, 1)
    assert body["kv_reconcile"]["missing"] == 0
    queues.down = True
    degraded = (await client.get("/api/v1/operator/health")).json()
    assert degraded["inbound_backlog"] is None and degraded["dlq_backlog"] is None


async def test_dlq_list_and_selective_retry(
    client: httpx.AsyncClient, session: AsyncSession, queues: FakeQueues
) -> None:
    """Listing shows metadata; retry moves only the chosen job and acks it in the DLQ."""
    await _users(session)
    queues.dlq = [
        {"lease_id": "l1", "attempts": 6, "body": json.dumps(_job("in/a.eml"))},
        {"lease_id": "l2", "attempts": 6, "body": json.dumps(_job("in/b.eml"))},
    ]
    await _login(client, "boss")
    listed = (await client.get("/api/v1/operator/dlq")).json()
    assert [item["r2_key"] for item in listed] == ["in/a.eml", "in/b.eml"]
    assert set(listed[0]) == {
        "lease_id",
        "r2_key",
        "rcpt_to",
        "raw_size",
        "received_at",
        "attempts",
    }
    moved = await client.post("/api/v1/operator/dlq/retry", json={"r2_keys": ["in/b.eml"]})
    assert moved.json() == {"moved": 1}
    assert queues.sent == [(get_settings().cf_queue_id_inbound, _job("in/b.eml"))]
    assert queues.acked == ["l2"]
