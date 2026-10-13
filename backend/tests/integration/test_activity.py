"""GET /me/activity: zero-filled daily totals and recent mail without personal data."""

# 3rd party imports
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.mail.types import MailKind, Outcome
from mailalias.services import mail_log
from tests.integration.harness import make_harness

pytestmark = pytest.mark.usefixtures("dispatched", "relaxed_rate_limits")


async def test_activity_totals_and_recent(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """Today's delivered forward/reply are counted; recent rows carry no addresses but the alias."""
    h = await make_harness(session)
    for kind in (MailKind.FORWARD, MailKind.FORWARD, MailKind.REPLY):
        await mail_log.record(
            session,
            kind=kind,
            outcome=Outcome.DELIVERED,
            user_id=h.user.id,
            alias_id=h.alias.id,
            size_bytes=100,
        )
    await mail_log.record(
        session,
        kind=MailKind.FORWARD,
        outcome=Outcome.QUARANTINED,
        reason="spam",
        user_id=h.user.id,
        alias_id=h.alias.id,
        spam_score=9.5,
    )
    await session.commit()
    login = await client.post("/api/v1/auth/login", json={"username": "pia", "password": "x" * 12})
    assert login.status_code == 200
    body = (await client.get("/api/v1/me/activity", params={"days": 7})).json()
    assert len(body["daily"]) == 7
    assert body["daily"][-1]["forwards"] == 2 and body["daily"][-1]["replies"] == 1
    assert all(day["forwards"] == 0 for day in body["daily"][:-1])
    latest = body["recent"][0]
    assert (latest["outcome"], latest["reason"], latest["spam_score"]) == (
        "quarantined",
        "spam",
        9.5,
    )
    assert latest["alias_address"] == h.alias.address
    assert set(latest) == {
        "id",
        "created_at",
        "kind",
        "outcome",
        "reason",
        "alias_id",
        "alias_address",
        "spam_score",
        "size_bytes",
    }
    assert (await client.get("/api/v1/me/activity", params={"days": 400})).status_code == 422
