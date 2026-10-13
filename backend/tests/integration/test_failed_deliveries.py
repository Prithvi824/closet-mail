"""Resend webhook (Svix-signed) handling, hard-bounce auto-disable, and the failed list API."""

# 1st party imports
import base64
import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

# 3rd party imports
import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from svix.webhooks import Webhook

# local imports
from mailalias.config import Settings, get_settings
from mailalias.mail.outbound import FakeMailer
from mailalias.mail.types import MailKind, Outcome
from mailalias.models import FailedDelivery, FailureKind, Recipient
from mailalias.security.crypto import lookup_hash
from mailalias.services import mail_log
from tests.integration.harness import Harness, make_harness

pytestmark = pytest.mark.usefixtures("dispatched", "relaxed_rate_limits")
SECRET = "whsec_" + base64.b64encode(os.urandom(24)).decode()
OWNER = "pia@example.com"


@pytest.fixture
def hook_settings(app: FastAPI) -> Settings:
    """Settings with a webhook secret, injected into the app.

    Args:
        app: Application.
    Returns:
        The settings.
    """
    settings = get_settings().model_copy(update={"resend_webhook_secret": SecretStr(SECRET)})
    app.dependency_overrides[get_settings] = lambda: settings
    return settings


def _event(
    event_type: str, email_id: str, to: str, bounce_type: str = "Permanent"
) -> dict[str, Any]:
    """A Resend-style event payload.

    Args:
        event_type: e.g. "email.bounced".
        email_id: Provider id of the message.
        to: Failed address.
        bounce_type: bounce.type for bounces.
    Returns:
        The payload.
    """
    data: dict[str, Any] = {"email_id": email_id, "to": [to], "from": "x@closetcompute.online"}
    if event_type == "email.bounced":
        data["bounce"] = {"type": bounce_type, "subType": "General", "message": "mailbox unknown"}
    return {"type": event_type, "created_at": datetime.now(UTC).isoformat(), "data": data}


async def _post(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
    event_id: str | None = None,
    secret: str = SECRET,
) -> httpx.Response:
    """Sign and post an event like Svix does.

    Args:
        client: API client.
        payload: Event payload.
        event_id: svix-id (random by default).
        secret: Signing secret.
    Returns:
        The response.
    """
    body = json.dumps(payload)
    msg_id = event_id or f"msg_{uuid.uuid4().hex}"
    now = datetime.now(UTC)
    signature = Webhook(secret).sign(msg_id, now, body)
    headers = {
        "svix-id": msg_id,
        "svix-timestamp": str(int(now.timestamp())),
        "svix-signature": signature,
        "content-type": "application/json",
    }
    return await client.post("/hooks/email-events", content=body, headers=headers)


async def _sent_forward(session: AsyncSession, h: Harness) -> str:
    """Log a delivered forward with a provider id, as the processor would.

    Args:
        session: Test session.
        h: Harness.
    Returns:
        The provider id.
    """
    provider_id = f"res-{uuid.uuid4()}"
    await mail_log.record(
        session,
        kind=MailKind.FORWARD,
        outcome=Outcome.DELIVERED,
        user_id=h.user.id,
        alias_id=h.alias.id,
        provider_id=provider_id,
    )
    await session.commit()
    return provider_id


async def _failures(session: AsyncSession, h: Harness) -> list[FailedDelivery]:
    """Failure rows of the harness user, oldest first.

    Args:
        session: Test session.
        h: Harness.
    Returns:
        Rows.
    """
    query = (
        select(FailedDelivery)
        .where(FailedDelivery.user_id == h.user.id)
        .order_by(FailedDelivery.created_at)
    )
    return list(await session.scalars(query))


@pytest.mark.usefixtures("hook_settings")
@pytest.mark.parametrize(
    ("event_type", "bounce_type", "kind"),
    [
        ("email.bounced", "Permanent", FailureKind.HARD),
        ("email.bounced", "Transient", FailureKind.SOFT),
        ("email.complained", "", FailureKind.COMPLAINT),
        ("email.delivery_delayed", "", FailureKind.DELAYED),
        ("email.suppressed", "", FailureKind.SUPPRESSED),
    ],
)
async def test_event_types_are_recorded_against_the_recipient(
    client: httpx.AsyncClient,
    session: AsyncSession,
    event_type: str,
    bounce_type: str,
    kind: FailureKind,
) -> None:
    """Each event type maps to its kind and links to the forward's user, alias and recipient."""
    h = await make_harness(session)
    provider_id = await _sent_forward(session, h)
    response = await _post(client, _event(event_type, provider_id, OWNER.upper(), bounce_type))
    assert response.status_code == 200 and response.json() == {"recorded": 1}
    (failure,) = await _failures(session, h)
    assert (failure.kind, failure.alias_id) == (kind, h.alias.id)
    assert failure.recipient_id == h.user.default_recipient_id


@pytest.mark.usefixtures("hook_settings")
async def test_bad_signature_and_duplicates(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """A wrong secret is refused; the same svix-id is recorded once."""
    h = await make_harness(session)
    provider_id = await _sent_forward(session, h)
    payload = _event("email.bounced", provider_id, OWNER)
    wrong = "whsec_" + base64.b64encode(os.urandom(24)).decode()
    assert (await _post(client, payload, secret=wrong)).status_code == 400
    assert (await _post(client, payload, "msg_same")).json() == {"recorded": 1}
    assert (await _post(client, payload, "msg_same")).json() == {"recorded": 0}
    assert len(await _failures(session, h)) == 1


async def test_missing_secret_is_503(client: httpx.AsyncClient) -> None:
    """Without a configured secret nothing can be verified."""
    response = await client.post("/hooks/email-events", content=b"{}")
    assert response.status_code == 503


@pytest.mark.usefixtures("hook_settings")
async def test_third_hard_bounce_disables_recipient_and_notifies(
    client: httpx.AsyncClient, session: AsyncSession, mailer: FakeMailer
) -> None:
    """Hard bounces 1-2 only count; the 3rd disables and mails the user's other address."""
    h = await make_harness(session)
    backup = "pia.backup@example.com"
    session.add(
        Recipient(
            user_id=h.user.id,
            email=backup,
            email_hash=lookup_hash(backup),
            verified_at=datetime.now(UTC),
        )
    )
    await session.commit()
    recipient = await session.get(Recipient, h.user.default_recipient_id)
    assert recipient is not None
    for expected in (1, 2):
        await _post(client, _event("email.bounced", await _sent_forward(session, h), OWNER))
        await session.refresh(recipient)
        assert (recipient.consecutive_hard_bounces, recipient.disabled_at) == (expected, None)
    await _post(client, _event("email.bounced", await _sent_forward(session, h), OWNER))
    await session.refresh(recipient)
    assert recipient.disabled_at is not None
    (notice,) = mailer.sent
    assert notice.rcpt_to == [backup]
    assert "disabled" in str(notice.message["Subject"])


@pytest.mark.usefixtures("hook_settings")
async def test_bounced_reply_never_counts_against_recipients(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """A reply's bounce is about the correspondent, even if the address is also a recipient."""
    h = await make_harness(session)
    provider_id = f"res-{uuid.uuid4()}"
    await mail_log.record(
        session,
        kind=MailKind.REPLY,
        outcome=Outcome.DELIVERED,
        user_id=h.user.id,
        alias_id=h.alias.id,
        provider_id=provider_id,
    )
    await session.commit()
    await _post(client, _event("email.bounced", provider_id, OWNER))
    (failure,) = await _failures(session, h)
    assert failure.recipient_id is None and failure.alias_id == h.alias.id
    recipient = await session.get(Recipient, h.user.default_recipient_id)
    assert recipient is not None and recipient.consecutive_hard_bounces == 0


@pytest.mark.usefixtures("hook_settings")
async def test_failed_deliveries_api(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """The user sees their failures with recipient and alias addresses."""
    h = await make_harness(session)
    await _post(client, _event("email.complained", await _sent_forward(session, h), OWNER))
    login = await client.post("/api/v1/auth/login", json={"username": "pia", "password": "x" * 12})
    assert login.status_code == 200
    (entry,) = (await client.get("/api/v1/failed-deliveries")).json()
    assert entry["kind"] == "complaint"
    assert (entry["recipient_email"], entry["alias_address"]) == (OWNER, h.alias.address)
