"""Request/response models for alias contacts (correspondents and their reply addresses)."""

# 1st party imports
import uuid
from datetime import datetime

# 3rd party imports
from pydantic import BaseModel, EmailStr

# local imports
from mailalias.models import Contact


class ContactCreate(BaseModel):
    """Start a conversation from an alias."""

    email: EmailStr


class ContactUpdate(BaseModel):
    """Block or unblock a contact."""

    blocked: bool


class ContactResponse(BaseModel):
    """A contact, including the address the owner writes to in order to reach them."""

    id: uuid.UUID
    alias_id: uuid.UUID
    email: str
    name: str | None
    token_address: str
    blocked: bool
    forwarded_count: int
    replied_count: int
    last_seen_at: datetime | None
    created_at: datetime

    @classmethod
    def build(cls, contact: Contact, reply_domain: str) -> "ContactResponse":
        """Serialise a contact.

        Args:
            contact: The contact.
            reply_domain: Settings.reply_domain.
        Returns:
            The response model.
        """
        return cls(
            id=contact.id,
            alias_id=contact.alias_id,
            email=contact.sender_email,
            name=contact.sender_name,
            token_address=f"{contact.token}@{reply_domain}",
            blocked=contact.blocked,
            forwarded_count=contact.forwarded_count,
            replied_count=contact.replied_count,
            last_seen_at=contact.last_seen_at,
            created_at=contact.created_at,
        )
