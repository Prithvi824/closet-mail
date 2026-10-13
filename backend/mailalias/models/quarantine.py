"""Quarantined (suspected spam) messages held in R2 for review."""

# 1st party imports
import uuid
from datetime import datetime

# 3rd party imports
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

# local imports
from mailalias.models.base import Base, Timestamps, UUIDPrimaryKey
from mailalias.security.crypto import EncryptedString


class QuarantineItem(UUIDPrimaryKey, Timestamps, Base):
    """A held message. The raw mail is encrypted in R2 under `r2_key`."""

    __tablename__ = "quarantine"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    alias_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("aliases.id", ondelete="SET NULL")
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL")
    )
    r2_key: Mapped[str] = mapped_column(String(128))
    spam_score: Mapped[float]
    sender: Mapped[str] = mapped_column(EncryptedString())
    subject: Mapped[str | None] = mapped_column(EncryptedString())
    expires_at: Mapped[datetime] = mapped_column(index=True)
    released_at: Mapped[datetime | None]
