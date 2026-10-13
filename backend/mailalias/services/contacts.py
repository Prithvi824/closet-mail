"""Contacts: external correspondents of an alias and their opaque reply tokens.

This is the only module that reads a correspondent's real address in plaintext.
"""

# 1st party imports
import uuid

# 3rd party imports
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.errors import NotFound
from mailalias.mail.addresses import TOKEN_RE, new_reply_token, normalize
from mailalias.models import Alias, Contact
from mailalias.security.crypto import lookup_hash
from mailalias.services import kv_sync

MAX_CREATE_ATTEMPTS = 5
MAX_NAME_LENGTH = 200


class ContactService:
    """Find, create and block contacts; resolve reply tokens."""

    def __init__(self, db: AsyncSession) -> None:
        """Build the service.

        Args:
            db: Database session.
        Returns:
            None.
        """
        self.db = db

    async def _find(self, alias_id: uuid.UUID, sender_hash: str) -> Contact | None:
        """Look up a contact by alias and sender hash.

        Args:
            alias_id: Alias id.
            sender_hash: lookup_hash of the sender address.
        Returns:
            The contact or None.
        """
        query = select(Contact).where(
            Contact.alias_id == alias_id, Contact.sender_hash == sender_hash
        )
        return await self.db.scalar(query)

    async def get_or_create(
        self, alias: Alias, sender_address: str, sender_name: str | None
    ) -> Contact:
        """Return the alias's contact for a sender, creating it (and its token) if new.

        Args:
            alias: Alias the sender wrote to.
            sender_address: Sender's real address.
            sender_name: Display name, if any; refreshed on existing contacts.
        Returns:
            The contact. New tokens are queued for KV after commit.
        """
        address = normalize(sender_address)
        sender_hash = lookup_hash(address)
        name = (sender_name or "").strip()[:MAX_NAME_LENGTH] or None
        for _ in range(MAX_CREATE_ATTEMPTS):
            contact = await self._find(alias.id, sender_hash)
            if contact is not None:
                if name and contact.sender_name != name:
                    contact.sender_name = name
                return contact
            contact = Contact(
                alias_id=alias.id,
                sender_email=address,
                sender_hash=sender_hash,
                sender_name=name,
                token=new_reply_token(),
            )
            try:
                async with self.db.begin_nested():
                    self.db.add(contact)
                    await self.db.flush()
            except IntegrityError:
                # A token collision or a concurrent insert of the same sender: look again.
                continue
            kv_sync.mark_contact(self.db, contact.id)
            return contact
        raise RuntimeError("could not allocate a contact token")

    async def list_for_alias(self, alias: Alias) -> list[Contact]:
        """Contacts of one alias, most recently seen first.

        Args:
            alias: Alias (ownership already checked by the caller).
        Returns:
            Contacts.
        """
        query = (
            select(Contact)
            .where(Contact.alias_id == alias.id)
            .order_by(Contact.last_seen_at.desc().nulls_last(), Contact.created_at.desc())
        )
        return list(await self.db.scalars(query))

    async def resolve_token(self, token: str) -> Contact | None:
        """Find the contact behind a reply token.

        Args:
            token: Local part of a reply address.
        Returns:
            The contact, or None for malformed or unknown tokens.
        """
        token = normalize(token)
        if not TOKEN_RE.fullmatch(token):
            return None
        return await self.db.scalar(select(Contact).where(Contact.token == token))

    async def get_owned(self, contact_id: uuid.UUID, owner_id: uuid.UUID) -> Contact:
        """Fetch a contact whose alias belongs to the owner.

        Args:
            contact_id: Contact id.
            owner_id: Expected alias owner.
        Returns:
            The contact. Raises NotFound otherwise.
        """
        query = (
            select(Contact)
            .join(Alias, Alias.id == Contact.alias_id)
            .where(Contact.id == contact_id, Alias.user_id == owner_id)
        )
        contact = await self.db.scalar(query)
        if contact is None:
            raise NotFound("Contact not found")
        return contact

    async def set_blocked(
        self, contact_id: uuid.UUID, owner_id: uuid.UUID, blocked: bool
    ) -> Contact:
        """Block or unblock a contact.

        Args:
            contact_id: Contact id.
            owner_id: Alias owner (ownership is enforced).
            blocked: New state.
        Returns:
            The contact.
        """
        contact = await self.get_owned(contact_id, owner_id)
        contact.blocked = blocked
        await self.db.flush()
        return contact

    def real_address(self, contact: Contact) -> str:
        """The correspondent's real address (the only plaintext read path).

        Args:
            contact: The contact.
        Returns:
            The decrypted sender address.
        """
        return contact.sender_email
