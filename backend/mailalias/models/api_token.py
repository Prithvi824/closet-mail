"""Scoped personal API tokens. Only a hash of the secret is stored."""

# 1st party imports
import uuid
from datetime import datetime

# 3rd party imports
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

# local imports
from mailalias.models.base import Base, Timestamps, UUIDPrimaryKey


class ApiToken(UUIDPrimaryKey, Timestamps, Base):
    """Bearer token `ma_<prefix>_<secret>`; looked up by prefix, verified by hash."""

    __tablename__ = "api_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(60))
    prefix: Mapped[str] = mapped_column(String(8), unique=True)
    secret_hash: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    last_used_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]
