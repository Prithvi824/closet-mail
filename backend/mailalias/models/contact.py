"""Contacts: external correspondents of an alias, each with an opaque reply token."""

# 1st party imports
import uuid
from datetime import datetime

# 3rd party imports
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

# local imports
from mailalias.models.base import Base, Timestamps, UUIDPrimaryKey
from mailalias.security.crypto import EncryptedString


class Contact(UUIDPrimaryKey, Timestamps, Base):
    """One sender seen by one alias. `token`@REPLY_DOMAIN routes replies back to them."""

    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("alias_id", "sender_hash", name="uq_contacts_alias_sender"),)

    alias_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("aliases.id", ondelete="CASCADE"), index=True
    )
    sender_email: Mapped[str] = mapped_column(EncryptedString())
    sender_hash: Mapped[str] = mapped_column(String(64), index=True)
    sender_name: Mapped[str | None] = mapped_column(EncryptedString())
    token: Mapped[str] = mapped_column(String(16), unique=True)
    blocked: Mapped[bool] = mapped_column(default=False)
    forwarded_count: Mapped[int] = mapped_column(default=0)
    replied_count: Mapped[int] = mapped_column(default=0)
    last_seen_at: Mapped[datetime | None]
