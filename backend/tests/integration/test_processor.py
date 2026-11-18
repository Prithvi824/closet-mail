"""MailProcessor + ForwardHandler against the dev database with a fake inbox and mailer."""

# 1st party imports

# 3rd party imports
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.config import get_settings
from mailalias.db import get_redis
from mailalias.mail.outbound import PermanentSendError
from mailalias.mail.processor import HEARTBEAT_KEY
from mailalias.mail.transform.banner import TEXT_START
from mailalias.mail.transform.pgp import PGP_ARMOR
from mailalias.mail.types import InboundEnvelope, MailKind, Outcome, RetryableError
from mailalias.models import (
    Alias,
    AliasState,
    Contact,
    DeliveryLog,
    FailedDelivery,
    FailureKind,
    Recipient,
    UsageDaily,
)
from mailalias.security.crypto import lookup_hash
from mailalias.services.contacts import ContactService
from mailalias.services.quota import global_key
from tests.eml import envelope
from tests.integration.harness import FlakyMailer, Harness, mail_logs, make_harness
from tests.pgp_keys import make_key

pytestmark = pytest.mark.usefixtures("dispatched")


async def test_forward_delivered_with_token_sender_and_banner(session: AsyncSession) -> None:
    """A forward reaches the owner from the token address with the banner; then acked."""
    h = await make_harness(session)
    lease = h.enqueue("fwd_alternative.eml")
    assert await h.processor.run_once() == 1
    (sent,) = h.mailer.sent
    contact = (await session.scalars(select(Contact).where(Contact.alias_id == h.alias.id))).one()
    token_address = f"{contact.token}@rp.closetcompute.online"
    assert sent.envelope_from == token_address
    assert sent.rcpt_to == ["pia@example.com"]
    assert sent.message["From"].addresses[0].addr_spec == token_address
    assert TEXT_START in sent.message.get_body(("plain",)).get_content()  # type: ignore[union-attr]
    assert "/a/" in sent.message.as_string()
    assert ContactService(session).real_address(contact) == "bob@example.net"
    assert h.inbox.acked == [lease] and h.inbox.deleted == ["in/lease-0.eml"]
    (log,) = await mail_logs(session, h)
    assert (log.kind, log.outcome, log.provider_id) == (
        MailKind.FORWARD,
        Outcome.DELIVERED,
        "fake-1",
    )


async def test_inactive_alias_is_discarded_and_counted(session: AsyncSession) -> None:
    """Inactive aliases accept and drop mail, bumping blocked_count."""
    h = await make_harness(session)
    h.alias.state = AliasState.INACTIVE
    await session.commit()
    lease = h.enqueue("fwd_alternative.eml")
    await h.processor.run_once()
    assert h.mailer.sent == [] and h.inbox.acked == [lease]
    await session.refresh(h.alias)
    assert h.alias.blocked_count == 1
    assert (await mail_logs(session, h))[0].reason == "alias_inactive"


async def test_blocked_contact_is_not_forwarded(session: AsyncSession) -> None:
    """A blocked sender's mail is BLOCKED."""
    h = await make_harness(session)
    contact = await ContactService(session).get_or_create(h.alias, "bob@example.net", None)
    contact.blocked = True
    await session.commit()
    h.enqueue("fwd_alternative.eml")
    await h.processor.run_once()
    assert h.mailer.sent == []
    assert (await mail_logs(session, h))[0].outcome == Outcome.BLOCKED


async def test_retryable_send_failure_retries_then_succeeds_once(session: AsyncSession) -> None:
    """A transient failure retries (no ack, raw kept, quota refunded); redelivery sends once."""
    h = await make_harness(session, FlakyMailer(RetryableError("smtp 451")))
    lease = h.enqueue("fwd_alternative.eml")
    await h.processor.run_once()
    assert h.inbox.acked == [] and h.inbox.deleted == []
    assert h.inbox.retried == [(lease, 60)]
    assert int(await get_redis().get(global_key()) or 0) == 0
    h.inbox.envelopes.append(envelope(h.alias.address))
    h.inbox.envelopes[-1] = InboundEnvelope(
        **{**h.inbox.envelopes[-1].__dict__, "lease_id": lease, "r2_key": "in/lease-0.eml"}
    )
    await h.processor.run_once()
    assert len(h.mailer.sent) == 1 and h.inbox.acked == [lease]


async def test_permanent_send_failure_is_discarded(session: AsyncSession) -> None:
    """A provider rejection is not retried."""
    h = await make_harness(session, FlakyMailer(PermanentSendError("550")))
    lease = h.enqueue("fwd_alternative.eml")
    await h.processor.run_once()
    assert h.inbox.acked == [lease]
    assert (await mail_logs(session, h))[0].reason == "send_failed"


async def test_global_cap_retries_in_an_hour(session: AsyncSession) -> None:
    """The provider cap keeps mail queued instead of dropping it."""
    h = await make_harness(session)
    await get_redis().set(global_key(), get_settings().outbound_daily_cap)
    lease = h.enqueue("fwd_alternative.eml")
    await h.processor.run_once()
    assert h.mailer.sent == [] and h.inbox.retried == [(lease, 3600)]


async def test_user_quota_discards_and_notifies_once(session: AsyncSession) -> None:
    """Over the hourly limit: discarded, owner notified once per day."""
    h = await make_harness(session)
    h.user.limits = {"forwards_per_hour": 1}
    await session.commit()
    for _ in range(3):
        h.enqueue("fwd_alternative.eml")
    await h.processor.run_once()
    assert len(h.mailer.sent) == 1
    assert [log.reason for log in await mail_logs(session, h)].count("quota") == 2
    assert len(h.notices.sent) == 1
    assert h.notices.sent[0].message["Subject"] == "Forwarding limit reached"


async def test_catchall_subdomain_creates_alias(session: AsyncSession) -> None:
    """Unknown address on a catch-all personal subdomain becomes a new active alias."""
    h = await make_harness(session)
    h.user.subdomain_catchall = True
    await session.commit()
    h.enqueue("fwd_alternative.eml", rcpt_to="newsletter@pia.closetcompute.online")
    await h.processor.run_once()
    assert len(h.mailer.sent) == 1
    created = await session.scalar(
        select(Alias).where(Alias.address == "newsletter@pia.closetcompute.online")
    )
    assert created is not None and created.state == AliasState.ACTIVE


async def test_unknown_subdomain_alias_without_catchall_is_discarded(
    session: AsyncSession,
) -> None:
    """Without catch-all the message is logged and dropped."""
    h = await make_harness(session)
    h.enqueue("fwd_alternative.eml", rcpt_to="x@pia.closetcompute.online")
    await h.processor.run_once()
    assert h.mailer.sent == [] and len(h.inbox.acked) == 1


async def test_own_forward_coming_back_is_dropped(session: AsyncSession) -> None:
    """Mail from one of our reply tokens is a loop."""
    h = await make_harness(session)
    h.enqueue(
        "fwd_alternative.eml",
        **{"From: Bob <bob@example.net>": "From: <abcdefghijklmnop@rp.closetcompute.online>"},
    )
    await h.processor.run_once()
    assert h.mailer.sent == []
    assert (await mail_logs(session, h))[0].reason == "loop"


async def test_dsn_at_token_is_recorded_not_forwarded(session: AsyncSession) -> None:
    """A DSN at a reply token becomes a failed delivery for its alias; nothing is sent."""
    h = await make_harness(session)
    contact = await ContactService(session).get_or_create(h.alias, "bob@example.org", None)
    await session.commit()
    lease = h.enqueue(
        "dsn_hard.eml", rcpt_to=f"{contact.token}@rp.closetcompute.online", mail_from=""
    )
    await h.processor.run_once()
    assert h.inbox.acked == [lease] and h.mailer.sent == []
    (failure,) = await session.scalars(
        select(FailedDelivery).where(FailedDelivery.alias_id == h.alias.id)
    )
    assert (failure.kind, failure.user_id, failure.recipient_id) == (
        FailureKind.HARD,
        h.user.id,
        None,
    )
    assert failure.detail is not None and "5.1.1" in failure.detail
    (log,) = await mail_logs(session, h)
    assert (log.kind, log.outcome) == (MailKind.BOUNCE, Outcome.BOUNCE_RECORDED)


async def test_drop_missing_raw_and_unexpected_errors(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DROP and missing R2 objects ack; unexpected exceptions retry with backoff."""
    h = await make_harness(session)
    dropped = h.enqueue("fwd_alternative.eml", rcpt_to="x@elsewhere.example")
    missing = h.enqueue("fwd_alternative.eml")
    del h.inbox.raw["in/lease-1.eml"]
    await h.processor.run_once()
    assert sorted(h.inbox.acked) == sorted([dropped, missing])

    def boom(*args: object) -> None:
        raise ValueError("bug")

    monkeypatch.setattr("mailalias.mail.processor.classify", boom)
    failing = h.enqueue("fwd_alternative.eml")
    await h.processor.run_once()
    assert h.inbox.retried == [(failing, 60)]


async def test_heartbeat_written(session: AsyncSession) -> None:
    """Each loop iteration refreshes the heartbeat key."""
    h = await make_harness(session)
    await h.processor.run_once()
    assert await get_redis().get(HEARTBEAT_KEY)
    assert 0 < await get_redis().ttl(HEARTBEAT_KEY) <= 120


async def test_recipient_with_pgp_key_gets_encrypted_forward(session: AsyncSession) -> None:
    """A recipient's PGP key turns the forward into inline PGP (built off the event loop)."""
    h = await make_harness(session)
    recipient = await session.get(Recipient, h.user.default_recipient_id)
    assert recipient is not None
    recipient.pgp_public_key = make_key("pia@example.com").public
    await session.commit()
    h.enqueue("fwd_alternative.eml")
    await h.processor.run_once()
    (sent,) = h.mailer.sent
    body = sent.message.get_body(("plain",))
    assert body is not None and body.get_content().startswith(PGP_ARMOR)
    assert TEXT_START.encode() not in sent.message.as_bytes()


async def _second_inbox(
    session: AsyncSession, h: Harness, email: str = "pia2@example.org"
) -> Recipient:
    """Add a verified second inbox for the harness user.

    Args:
        session: Test session.
        h: Harness.
        email: Inbox address.
    Returns:
        The recipient.
    """
    recipient = Recipient(
        user_id=h.user.id,
        email=email,
        email_hash=lookup_hash(email),
        verified_at=h.user.created_at,
    )
    session.add(recipient)
    await session.flush()
    return recipient


async def _drain(h: Harness) -> None:
    """Run the processor until the fake inbox is empty.

    Args:
        h: Harness.
    Returns:
        None.
    """
    while h.inbox.envelopes:
        await h.processor.run_once()


async def test_forward_to_two_inboxes_logs_each_delivery_and_sender(
    session: AsyncSession,
) -> None:
    """Each inbox gets its own delivery row and provider id; the log keeps time and sender."""
    h = await make_harness(session)
    second = await _second_inbox(session, h)
    first = await session.get(Recipient, h.user.default_recipient_id)
    assert first is not None
    h.alias.recipients = [first, second]
    await session.commit()
    h.enqueue("fwd_alternative.eml")
    await h.processor.run_once()
    assert len(h.mailer.sent) == 2
    (log,) = await mail_logs(session, h)
    rows = (
        await session.scalars(select(DeliveryLog).where(DeliveryLog.mail_log_id == log.id))
    ).all()
    assert {(r.recipient_id, r.provider_id) for r in rows} == {
        (first.id, "fake-1"),
        (second.id, "fake-2"),
    }
    assert log.sender_domain == "example.net"
    assert log.received_at is not None


async def test_catchall_is_not_limited_by_hourly_alias_creation(session: AsyncSession) -> None:
    """More new catch-all addresses than the hourly create limit all become aliases."""
    h = await make_harness(session)
    h.user.subdomain_catchall = True
    await session.commit()
    count = get_settings().user_alias_creates_per_hour + 5
    for index in range(count):
        h.enqueue("fwd_alternative.eml", rcpt_to=f"shop{index}@pia.closetcompute.online")
    await _drain(h)
    created = (
        await session.scalars(
            select(Alias).where(Alias.user_id == h.user.id, Alias.local_part.like("shop_%"))
        )
    ).all()
    assert len(created) == count


async def test_unknown_address_on_a_subdomain_is_logged_to_it(session: AsyncSession) -> None:
    """A drop for an unknown address on an existing subdomain counts toward that subdomain."""
    h = await make_harness(session)
    h.enqueue("fwd_alternative.eml", rcpt_to="x@pia.closetcompute.online")
    await h.processor.run_once()
    (log,) = await mail_logs(session, h)
    assert (log.outcome, log.reason, log.alias_id) == (Outcome.DISCARDED, "unknown_alias", None)


async def test_redelivered_forward_is_not_counted_twice(session: AsyncSession) -> None:
    """A message processed again after it was fully delivered sends nothing and counts once."""
    h = await make_harness(session)
    lease = h.enqueue("fwd_alternative.eml")
    await h.processor.run_once()
    h.inbox.envelopes.append(envelope(h.alias.address))
    h.inbox.envelopes[-1] = InboundEnvelope(
        **{**h.inbox.envelopes[-1].__dict__, "lease_id": lease, "r2_key": "in/lease-0.eml"}
    )
    await h.processor.run_once()
    assert len(h.mailer.sent) == 1
    usage = (await session.scalars(select(UsageDaily).where(UsageDaily.user_id == h.user.id))).one()
    assert (usage.received, usage.forwards) == (1, 1)
    await session.refresh(h.alias)
    assert h.alias.forwarded_count == 1
