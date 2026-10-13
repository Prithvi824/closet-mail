"""Blocklist API and forward-time blocking; one-click banner actions (GET is read-only)."""

# 1st party imports
import re

# 3rd party imports
import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.mail.types import Outcome
from mailalias.models import AliasState, Contact
from tests.integration.harness import Harness, mail_logs, make_harness

pytestmark = pytest.mark.usefixtures("dispatched", "relaxed_rate_limits")
ACTION_URL_RE = re.compile(
    r"(?P<label>Block sender|Disable alias): https?://[^/\s]+(?P<path>/a/\S+)"
)


async def _login(client: httpx.AsyncClient) -> None:
    """Log in as the harness user.

    Args:
        client: API client.
    Returns:
        None.
    """
    response = await client.post(
        "/api/v1/auth/login", json={"username": "pia", "password": "x" * 12}
    )
    assert response.status_code == 200


async def _forward_links(h: Harness) -> dict[str, str]:
    """Forward one message and pull the banner's action paths out of the text part.

    Args:
        h: Harness.
    Returns:
        {"Block sender": "/a/...", "Disable alias": "/a/..."}.
    """
    h.enqueue("fwd_alternative.eml")
    await h.processor.run_once()
    text = h.mailer.sent[-1].message.get_body(("plain",)).get_content()  # type: ignore[union-attr]
    return {m["label"]: m["path"] for m in ACTION_URL_RE.finditer(text)}


async def test_blocklist_api(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """Add (normalised), refuse duplicates and junk, list, delete."""
    await make_harness(session)
    await _login(client)
    created = await client.post("/api/v1/blocklist", json={"pattern": "@Example.NET"})
    assert created.status_code == 201
    assert (created.json()["pattern"], created.json()["kind"]) == ("example.net", "domain")
    duplicate = await client.post("/api/v1/blocklist", json={"pattern": "example.net"})
    assert duplicate.status_code == 409
    junk = await client.post("/api/v1/blocklist", json={"pattern": "not a domain"})
    assert junk.status_code == 422
    assert [e["pattern"] for e in (await client.get("/api/v1/blocklist")).json()] == ["example.net"]
    deleted = await client.delete(f"/api/v1/blocklist/{created.json()['id']}")
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/blocklist")).json() == []


async def test_blocked_domain_is_not_forwarded_and_creates_no_contact(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """A blocked parent domain blocks its subdomains; no contact or spam check happens."""
    h = await make_harness(session)
    await _login(client)
    await client.post("/api/v1/blocklist", json={"pattern": "example.net"})
    h.enqueue(
        "fwd_alternative.eml",
        **{"From: Bob <bob@example.net>": "From: Bob <bob@mail.example.net>"},
    )
    await h.processor.run_once()
    assert h.mailer.sent == [] and h.spam.calls == []
    (log,) = await mail_logs(session, h)
    assert (log.outcome, log.reason) == (Outcome.BLOCKED, "blocklist")
    assert (
        await session.scalars(select(Contact).where(Contact.alias_id == h.alias.id))
    ).all() == []


async def test_block_link_get_is_read_only_and_post_blocks(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """GET shows a confirmation; POST blocks; the next forward from the sender is BLOCKED."""
    h = await make_harness(session)
    path = (await _forward_links(h))["Block sender"]
    page = await client.get(path)
    assert page.status_code == 200 and '<form method="post">' in page.text
    contact = (await session.scalars(select(Contact).where(Contact.alias_id == h.alias.id))).one()
    await session.refresh(contact)
    assert contact.blocked is False
    done = await client.post(path)
    assert done.status_code == 200 and "blocked" in done.text
    await session.refresh(contact)
    assert contact.blocked is True
    h.enqueue("fwd_alternative.eml")
    await h.processor.run_once()
    assert len(h.mailer.sent) == 1
    assert (await mail_logs(session, h))[-1].outcome == Outcome.BLOCKED


async def test_disable_link_deactivates_alias(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """POST on the disable link makes the alias inactive."""
    h = await make_harness(session)
    path = (await _forward_links(h))["Disable alias"]
    assert (await client.post(path)).status_code == 200
    await session.refresh(h.alias)
    assert h.alias.state == AliasState.INACTIVE


async def test_tampered_or_garbage_links_are_rejected(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """A modified signature or a random token gives the error page and changes nothing."""
    h = await make_harness(session)
    path = (await _forward_links(h))["Block sender"]
    tampered = path[:-2] + ("AA" if not path.endswith("AA") else "BB")
    for bad in (tampered, "/a/not-a-token"):
        assert (await client.get(bad)).status_code == 404
        assert (await client.post(bad)).status_code == 404
    contact = (await session.scalars(select(Contact).where(Contact.alias_id == h.alias.id))).one()
    await session.refresh(contact)
    assert contact.blocked is False
