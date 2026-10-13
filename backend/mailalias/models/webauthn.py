"""Passkeys (WebAuthn credentials) registered as a second factor."""

# 1st party imports
import uuid
from datetime import datetime

# 3rd party imports
from sqlalchemy import ForeignKey, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

# local imports
from mailalias.models.base import Base, Timestamps, UUIDPrimaryKey


class WebAuthnCredential(UUIDPrimaryKey, Timestamps, Base):
    """One authenticator's public key; `credential_id` is base64url as sent by the browser."""

    __tablename__ = "webauthn_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    credential_id: Mapped[str] = mapped_column(String(1024), unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(default=0)
    name: Mapped[str] = mapped_column(String(60))
    transports: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    last_used_at: Mapped[datetime | None]
