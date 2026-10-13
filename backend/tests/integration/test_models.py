"""Models round-trip through Postgres with encrypted columns stored as ciphertext."""

# 3rd party imports
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.models import Alias, AliasKind, AliasState, Contact, Recipient, User
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
    user.default_recipient_id = recipient.id
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
    assert loaded_user.default_recipient_id == recipient.id

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
