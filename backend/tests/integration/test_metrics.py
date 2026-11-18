"""Metrics: the operator overview and each subdomain's activity (who sent what, to whom, when)."""

# 1st party imports
from datetime import UTC, datetime, timedelta

# 3rd party imports
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.config import get_settings
from mailalias.db import get_redis
from mailalias.mail.types import MailKind, Outcome
from mailalias.models import Alias, Recipient, User, UserRole
from mailalias.security.crypto import lookup_hash
from mailalias.services import mail_log
from mailalias.services.aliases import AliasService
from mailalias.services.contacts import ContactService
from mailalias.services.quota import share_key
from mailalias.services.users import UserService
from tests.integration.harness import default_inbox, sub

pytestmark = pytest.mark.usefixtures("dispatched", "relaxed_rate_limits")
PASSWORD = "correct horse battery"


async def _subdomain(session: AsyncSession, label: str) -> tuple[User, Alias, Recipient, Recipient]:
    """A subdomain with an alias and two inboxes.

    Args:
        session: Test session.
        label: Subdomain label.
    Returns:
        (user, alias, first inbox, second inbox).
    """
    user = await UserService(session).create_user(label, f"{label}@example.com", PASSWORD)
    alias = await AliasService(session, get_settings()).create(user, local_part=f"{label}-shop")
    second = Recipient(
        user_id=user.id,
        email=f"{label}.two@example.org",
        email_hash=lookup_hash(f"{label}.two@example.org"),
        verified_at=datetime.now(UTC),
    )
    session.add(second)
    await session.flush()
    return user, alias, await default_inbox(session, user), second


async def _forward(
    session: AsyncSession,
    user: User,
    alias: Alias,
    sender: str,
    inboxes: list[Recipient],
    outcome: Outcome = Outcome.DELIVERED,
) -> None:
    """Log one forward from `sender` delivered to `inboxes`.

    Args:
        session: Test session.
        user, alias: Subdomain and alias.
        sender: Sender address.
        inboxes: Destinations (ignored unless delivered).
        outcome: What happened.
    Returns:
        None.
    """
    contact = await ContactService(session).get_or_create(alias, sender, None)
    delivered = outcome == Outcome.DELIVERED
    await mail_log.record(
        session,
        kind=MailKind.FORWARD,
        outcome=outcome,
        user_id=user.id,
        alias_id=alias.id,
        contact_id=contact.id,
        size_bytes=100,
        sender_address=sender,
        received_at=datetime.now(UTC) - timedelta(minutes=len(inboxes)),
        deliveries=[
            mail_log.DeliveryRecord(inbox.id, f"p-{inbox.id}-{sender}") for inbox in inboxes
        ]
        if delivered
        else (),
    )


async def _seed(session: AsyncSession, client: httpx.AsyncClient) -> None:
    """Two subdomains with mail from two sender domains; operator boss signed in.

    Args:
        session: Test session.
        client: HTTP client.
    Returns:
        None.
    """
    await UserService(session).create_user("boss", "boss@example.com", PASSWORD, UserRole.ADMIN)
    acme, acme_alias, acme_one, acme_two = await _subdomain(session, "acme")
    beta, beta_alias, beta_one, _ = await _subdomain(session, "beta")
    await _forward(session, acme, acme_alias, "bob@shop.example", [acme_one, acme_two])
    await _forward(session, acme, acme_alias, "ann@shop.example", [acme_one])
    await _forward(session, acme, acme_alias, "spam@junk.example", [], Outcome.QUARANTINED)
    await _forward(session, beta, beta_alias, "news@junk.example", [beta_one])
    await session.commit()
    await get_redis().set(share_key(acme.id), 3)
    login = await client.post("/api/v1/auth/login", json={"username": "boss", "password": PASSWORD})
    assert login.status_code == 200


async def test_overview_totals_per_subdomain_and_top_sender_domains(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Counts add up across subdomains and sender domains come back decrypted."""
    await _seed(session, client)
    body = (await client.get("/api/v1/operator/overview", params={"days": 7})).json()
    assert body["days"] == 7 and len(body["daily"]) == 7
    assert body["totals"] == {
        "received": 4,
        "delivered": 3,
        "quarantined": 1,
        "blocked": 0,
        "discarded": 0,
        "replies": 0,
    }
    assert body["daily"][-1]["received"] == 4
    per = {item["label"]: item for item in body["per_subdomain"]}
    assert per["acme"]["totals"]["received"] == 3 and per["beta"]["totals"]["received"] == 1
    assert (per["acme"]["sends_today"], per["acme"]["send_share"]) == (3, 40)
    assert body["top_sender_domains"] == [
        {"key": "junk.example", "count": 2},
        {"key": "shop.example", "count": 2},
    ] or body["top_sender_domains"] == [
        {"key": "shop.example", "count": 2},
        {"key": "junk.example", "count": 2},
    ]
    assert body["send_cap"] == get_settings().outbound_daily_cap


async def test_subdomain_activity_shows_senders_and_every_destination(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Recent mail names the sender, the alias and each inbox with its delivery status."""
    await _seed(session, client)
    body = (await client.get(sub("acme", "/activity"), params={"days": 30})).json()
    assert body["totals"]["received"] == 3
    assert {item["key"] for item in body["top_sender_domains"]} == {"shop.example", "junk.example"}
    assert {item["key"] for item in body["top_senders"]} == {
        "bob@shop.example",
        "ann@shop.example",
        "spam@junk.example",
    }
    assert body["per_alias"] == [{"key": "acme-shop@closetcompute.online", "count": 3}]
    assert {(item["key"], item["count"]) for item in body["per_inbox"]} == {
        ("acme@example.com", 2),
        ("acme.two@example.org", 1),
    }
    bob = next(event for event in body["recent"] if event["sender"] == "bob@shop.example")
    assert bob["alias_address"] == "acme-shop@closetcompute.online"
    assert bob["sender_domain"] == "shop.example"
    assert sorted((d["inbox"], d["status"]) for d in bob["destinations"]) == [
        ("acme.two@example.org", "sent"),
        ("acme@example.com", "sent"),
    ]
    assert (body["page"], body["has_more"]) == (1, False)


async def test_activity_never_mixes_subdomains(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """beta's activity holds only beta's mail."""
    await _seed(session, client)
    body = (await client.get(sub("beta", "/activity"))).json()
    assert [event["sender"] for event in body["recent"]] == ["news@junk.example"]
    assert body["totals"]["received"] == 1


async def test_windows_are_validated(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """Days outside 1..90 are refused."""
    await _seed(session, client)
    for days in (0, 91):
        assert (
            await client.get("/api/v1/operator/overview", params={"days": days})
        ).status_code == 422
        assert (
            await client.get(sub("acme", "/activity"), params={"days": days})
        ).status_code == 422
