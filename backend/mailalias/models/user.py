"""User accounts and their per-user preferences."""

# 1st party imports
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

# 3rd party imports
from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

# local imports
from mailalias.models.base import Base, Timestamps, UUIDPrimaryKey, pg_enum
from mailalias.security.crypto import EncryptedString


class UserRole(StrEnum):
    """Authorisation level."""

    USER = "user"
    ADMIN = "admin"


class BannerPosition(StrEnum):
    """Where the forwarding banner is placed in forwarded mail."""

    TOP = "top"
    BOTTOM = "bottom"
    OFF = "off"


class AliasFormat(StrEnum):
    """Generator used for random aliases."""

    WORDS = "words"
    CHARS = "chars"


class User(UUIDPrimaryKey, Timestamps, Base):
    """An account. Email is encrypted; `email_hash` is used for lookups."""

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(30), unique=True)
    email: Mapped[str] = mapped_column(EncryptedString())
    email_hash: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str]
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole, "user_role"), default=UserRole.USER)
    totp_secret: Mapped[str | None] = mapped_column(EncryptedString())
    totp_enabled: Mapped[bool] = mapped_column(default=False)
    backup_codes_hash: Mapped[list[str]] = mapped_column(JSONB, default=list)
    default_recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recipients.id", ondelete="SET NULL", use_alter=True)
    )
    banner_position: Mapped[BannerPosition] = mapped_column(
        pg_enum(BannerPosition, "banner_position"), default=BannerPosition.TOP
    )
    alias_format: Mapped[AliasFormat] = mapped_column(
        pg_enum(AliasFormat, "alias_format"), default=AliasFormat.WORDS
    )
    strip_trackers: Mapped[bool] = mapped_column(default=True)
    subdomain_catchall: Mapped[bool] = mapped_column(default=False)
    limits: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    disabled_at: Mapped[datetime | None]
