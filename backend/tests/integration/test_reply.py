"""ReplyHandler through the processor, and the contacts API (send-from-alias, blocking)."""

# 3rd party imports
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.config import get_settings
from mailalias.mail.types import MailKind, Outcome
from mailalias.models import Alias, Contact
from mailalias.services.aliases import AliasService
from mailalias.services.contacts import ContactService
from tests.integration.harness import Harness, mail_logs, make_harness

pytestmark = pytest.mark.usefixtures("dispatched")
OWNER = "pia@example.com"  # the harness user's verified default recipient


async def _contact(session: AsyncSession, alias: Alias, address: str, name: str) -> Contact:
    """Create and commit a contact.

    Args:
        session: Test session.
        alias: Alias.
        address: Correspondent address.
        name: Display name.
    Returns:
        The contact.
    """
    contact = await ContactService(session).get_or_create(alias, address, name)
    await session.commit()
    return contact


def _enqueue_reply(
    h: Harness,
    token: str,
    *,
    sender: str = OWNER,
    envelope_from: str = OWNER,
    dmarc: str = "pass",
    cc: str = "Nobody <nobody@example.org>",
    rcpt_token: str | None = None,
) -> str:
    """Queue the owner-reply fixture.

    Args:
        h: Harness.
        token: Token in the To header.
        sender: Header From address.
        envelope_from: Envelope sender.
        dmarc: DMARC verdict stamped by "Cloudflare".
        cc: Cc header.
        rcpt_token: Envelope recipient token (defaults to `token`).
    Returns:
        The lease id.
    """
    return h.enqueue(
        "owner_reply_gmail.eml",
        rcpt_to=f"{rcpt_token or token}@rp.closetcompute.online",
        mail_from=envelope_from,
        **{"{TOKEN}": token, "{FROM}": sender, "{DMARC}": dmarc, "{CC}": cc},
    )


async def test_valid_reply_goes_out_from_alias(session: AsyncSession) -> None:
    """Sent from the alias to the contact only; no owner address anywhere; logged."""
    h = await make_harness(session)
    bob = await _contact(session, h.alias, "bob@example.net", "Bob")
    lease = _enqueue_reply(h, bob.token)
    await h.processor.run_once()
    (sent,) = h.mailer.sent
    assert sent.envelope_from == h.alias.address
    assert sent.rcpt_to == ["bob@example.net"]
    assert sent.message["From"] == h.alias.address
    assert OWNER.encode() not in sent.message.as_bytes().lower()
    assert h.inbox.acked == [lease]
    (log,) = await mail_logs(session, h)
    assert (log.kind, log.outcome) == (MailKind.REPLY, Outcome.DELIVERED)
    await session.refresh(bob)
    assert bob.replied_count == 1
    assert h.notices.sent and "were removed" in str(h.notices.sent[0].message["Subject"])


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        (
            {"sender": "mallory@evil.example", "envelope_from": "mallory@evil.example"},
            "unauthorized_sender",
        ),
        ({"envelope_from": "mallory@evil.example"}, "unauthorized_sender"),
        ({"sender": "mallory@evil.example"}, "unauthorized_sender"),
        ({"dmarc": "fail"}, "dmarc_fail"),
        ({"dmarc": "none"}, "dmarc_fail"),
    ],
)
async def test_rejected_replies_send_nothing(
    session: AsyncSession, overrides: dict[str, str], reason: str
) -> None:
    """Spoofed senders and DMARC failures are dropped and the owner is told once."""
    h = await make_harness(session)
    bob = await _contact(session, h.alias, "bob@example.net", "Bob")
    _enqueue_reply(h, bob.token, **overrides)
    _enqueue_reply(h, bob.token, **overrides)
    await h.processor.run_once()
    assert h.mailer.sent == []
    logs = await mail_logs(session, h)
    assert [(log.outcome, log.reason) for log in logs] == [(Outcome.REJECTED_REPLY, reason)] * 2
    assert len(h.notices.sent) == 1


async def test_reply_disabled_and_deleted_alias(session: AsyncSession) -> None:
    """Aliases with replies off, or deleted, do not send."""
    h = await make_harness(session)
    bob = await _contact(session, h.alias, "bob@example.net", "Bob")
    h.alias.reply_enabled = False
    await session.commit()
    _enqueue_reply(h, bob.token)
    await h.processor.run_once()
    await AliasService(session, get_settings()).delete(h.user, h.alias.id)
    await session.commit()
    _enqueue_reply(h, bob.token)
    await h.processor.run_once()
    assert h.mailer.sent == []
    assert [log.reason for log in await mail_logs(session, h)] == [
        "reply_disabled",
        "alias_deleted",
    ]


async def test_unknown_token_is_rejected_silently(session: AsyncSession) -> None:
    """No contact behind the token: rejected, nobody to notify."""
    h = await make_harness(session)
    lease = _enqueue_reply(h, "zzzzzzzzzzzzzzzz")
    await h.processor.run_once()
    assert h.mailer.sent == [] and h.notices.sent == [] and h.inbox.acked == [lease]


async def test_mixed_recipients_filtered_per_alias(session: AsyncSession) -> None:
    """Same-alias tokens map to real addresses; other aliases' tokens and outsiders go."""
    h = await make_harness(session)
    bob = await _contact(session, h.alias, "bob@example.net", "Bob")
    carol = await _contact(session, h.alias, "carol@example.org", "Carol")
    other_alias = await AliasService(session, get_settings()).create(h.user)
    dave = await _contact(session, other_alias, "dave@example.org", "Dave")
    cc = (
        f"Carol <{carol.token}@rp.closetcompute.online>, "
        f"Dave <{dave.token}@rp.closetcompute.online>, outsider@example.org"
    )
    _enqueue_reply(h, bob.token, cc=cc)
    _enqueue_reply(h, bob.token, cc=cc, rcpt_token=carol.token)
    await h.processor.run_once()
    assert [m.rcpt_to for m in h.mailer.sent] == [["bob@example.net"], ["carol@example.org"]]
    for sent in h.mailer.sent:
        assert [a.addr_spec for a in sent.message["Cc"].addresses] == ["carol@example.org"]
        raw = sent.message.as_bytes()
        assert b"dave@example.org" not in raw and b"outsider@example.org" not in raw
    assert len(h.notices.sent) == 1


async def test_reply_quota(session: AsyncSession) -> None:
    """Over the daily reply limit the reply is discarded with a notice."""
    h = await make_harness(session)
    h.user.limits = {"replies_per_day": 0}
    await session.commit()
    bob = await _contact(session, h.alias, "bob@example.net", "Bob")
    _enqueue_reply(h, bob.token, cc="")
    await h.processor.run_once()
    assert h.mailer.sent == []
    assert (await mail_logs(session, h))[0].reason == "quota"
    assert "reply limit" in h.notices.sent[0].message.get_content()


@pytest.mark.usefixtures("relaxed_rate_limits")
async def test_contacts_api(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """Start a conversation, list contacts, block, and refuse service addresses."""
    h = await make_harness(session)
    login = await client.post("/api/v1/auth/login", json={"username": "pia", "password": "x" * 12})
    assert login.status_code == 200
    url = f"/api/v1/aliases/{h.alias.id}/contacts"
    created = await client.post(url, json={"email": "New.Person@Example.org"})
    assert created.status_code == 201
    body = created.json()
    assert body["email"] == "new.person@example.org"
    assert body["token_address"].endswith("@rp.closetcompute.online")
    again = await client.post(url, json={"email": "new.person@example.org"})
    assert again.json()["id"] == body["id"]
    assert [c["id"] for c in (await client.get(url)).json()] == [body["id"]]
    blocked = await client.patch(f"/api/v1/contacts/{body['id']}", json={"blocked": True})
    assert blocked.json()["blocked"] is True
    own = await client.post(url, json={"email": "x@closetcompute.online"})
    assert own.status_code == 422
