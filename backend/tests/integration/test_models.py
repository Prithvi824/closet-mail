"""Models round-trip through Postgres with encrypted columns stored as ciphertext."""

# 1st party imports
from datetime import UTC, datetime

# 3rd party imports
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.mail.types import MailKind, Outcome
from mailalias.models import (
    Alias,
    AliasKind,
    AliasState,
    Contact,
    DeliveryLog,
    DeliveryStatus,
    MailLog,
    Recipient,
    SubdomainState,
    SubdomainStatus,
    User,
)
from mailalias.security.crypto import lookup_hash


async def test_user_recipient_alias_contact_round_trip(session: AsyncSession) -> None:
    """Insert a linked user/recipient/alias/contact and read them back decrypted.

    Args:
        session: Rolled-back test session.
    Returns:
        None.
    """
    user = User(
        username="alice",
        email="Alice@Example.com",
        email_hash=lookup_hash("Alice@Example.com"),
        password_hash="x",
    )
    session.add(user)
    await session.flush()
    recipient = Recipient(
        user_id=user.id, email="alice@example.com", email_hash=lookup_hash("alice@example.com")
    )
    session.add(recipient)
    await session.flush()
    alias = Alias(
        user_id=user.id,
        local_part="sunny.river42",
        domain="closetcompute.online",
        address="sunny.river42@closetcompute.online",
        kind=AliasKind.SHARED,
        description="newsletter",
    )
    alias.recipients = [recipient]
    session.add(alias)
    await session.flush()
    contact = Contact(
        alias_id=alias.id,
        sender_email="bob@shop.example",
        sender_hash=lookup_hash("bob@shop.example"),
        sender_name="Bob",
        token="abcdefghijklmnop",
    )
    session.add(contact)
    await session.commit()
    session.expunge_all()

    loaded_user = await session.scalar(
        select(User).where(User.email_hash == lookup_hash("alice@example.com"))
    )
    assert loaded_user is not None
    assert loaded_user.email == "Alice@Example.com"

    loaded_alias = await session.scalar(select(Alias).where(Alias.address == alias.address))
    assert loaded_alias is not None
    assert loaded_alias.state is AliasState.ACTIVE
    assert loaded_alias.description == "newsletter"

    loaded_contact = await session.scalar(
        select(Contact).where(Contact.token == "abcdefghijklmnop")
    )
    assert loaded_contact is not None
    assert (loaded_contact.sender_email, loaded_contact.sender_name) == ("bob@shop.example", "Bob")

    # Raw column values must be ciphertext, while addresses/tokens stay plaintext for lookups.
    raw = (
        await session.execute(
            text(
                "select u.email, a.description, a.address, c.sender_email, c.token "
                "from users u join aliases a on a.user_id = u.id "
                "join contacts c on c.alias_id = a.id"
            )
        )
    ).one()
    assert "example.com" not in raw.email.lower()
    assert raw.description != "newsletter"
    assert raw.address == "sunny.river42@closetcompute.online"
    assert "shop.example" not in raw.sender_email
    assert raw.token == "abcdefghijklmnop"


async def test_delivery_log_round_trip(session: AsyncSession) -> None:
    """A delivery row links a mail log row to one inbox and reads back with its status.

    Args:
        session: Rolled-back test session.
    Returns:
        None.
    """
    user = User(username="dora", email="d@example.com", email_hash=lookup_hash("d@example.com"))
    user.password_hash = "x"
    session.add(user)
    await session.flush()
    recipient = Recipient(
        user_id=user.id, email="d@example.com", email_hash=lookup_hash("d@example.com")
    )
    received = datetime(2026, 11, 1, 9, 30, tzinfo=UTC)
    log = MailLog(
        user_id=user.id,
        kind=MailKind.FORWARD,
        outcome=Outcome.DELIVERED,
        received_at=received,
        sender_domain_hash=lookup_hash("shop.example"),
        sender_domain="shop.example",
    )
    session.add_all([recipient, log])
    await session.flush()
    session.add(
        DeliveryLog(
            mail_log_id=log.id,
            user_id=user.id,
            recipient_id=recipient.id,
            provider_id="re_123",
            status_at=received,
        )
    )
    await session.commit()
    session.expunge_all()

    row = await session.scalar(select(DeliveryLog).where(DeliveryLog.provider_id == "re_123"))
    assert row is not None
    assert (row.mail_log_id, row.recipient_id) == (log.id, recipient.id)
    assert row.status is DeliveryStatus.SENT
    loaded = await session.get(MailLog, log.id)
    assert loaded is not None
    assert loaded.received_at == received
    assert loaded.sender_domain == "shop.example"
    raw = await session.scalar(
        text("select sender_domain from mail_log where id = :i"), {"i": log.id}
    )
    assert raw is not None and "shop.example" not in raw


async def test_subdomain_without_login_and_its_status_round_trip(session: AsyncSession) -> None:
    """A subdomain row needs no email or password; its status row reads back.

    Args:
        session: Rolled-back test session.
    Returns:
        None.
    """
    user = User(username="acme", display_name="Acme Ltd", notes="pays yearly")
    session.add(user)
    await session.flush()
    checked = datetime(2026, 11, 18, 8, 0, tzinfo=UTC)
    session.add(
        SubdomainStatus(
            user_id=user.id,
            state=SubdomainState.DNS_MISSING,
            mx_ok=False,
            spf_ok=None,
            kv_ok=True,
            detail="MX records missing",
            checked_at=checked,
        )
    )
    await session.commit()
    session.expunge_all()
    loaded = await session.scalar(select(User).where(User.username == "acme"))
    assert loaded is not None
    assert (loaded.email, loaded.password_hash, loaded.retired_at) == (None, None, None)
    assert (loaded.display_name, loaded.notes) == ("Acme Ltd", "pays yearly")
    status = await session.get(SubdomainStatus, user.id)
    assert status is not None
    assert (status.state, status.mx_ok, status.checked_at) == (
        SubdomainState.DNS_MISSING,
        False,
        checked,
    )
    raw = await session.scalar(text("select notes from users where username = 'acme'"))
    assert raw is not None and "yearly" not in raw
