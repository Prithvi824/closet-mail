"""Admin-issued invitations; the only way to create an account in phase 1."""

# 1st party imports
import uuid
from datetime import datetime

# 3rd party imports
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

# local imports
from mailalias.models.base import Base, Timestamps, UUIDPrimaryKey
from mailalias.security.crypto import EncryptedString


class Invite(UUIDPrimaryKey, Timestamps, Base):
    """A single-use invite link. Only the token's hash is stored."""

    __tablename__ = "invites"

    email: Mapped[str] = mapped_column(EncryptedString())
    email_hash: Mapped[str] = mapped_column(String(64), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
