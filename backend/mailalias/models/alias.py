"""Aliases and their recipient links. Addresses are public, so stored in plaintext."""

# 1st party imports
import uuid
from datetime import datetime
from enum import StrEnum

# 3rd party imports
from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

# local imports
from mailalias.models.base import Base, Timestamps, UUIDPrimaryKey, pg_enum
from mailalias.models.label import Label, alias_labels
from mailalias.models.recipient import Recipient
from mailalias.security.crypto import EncryptedString


class AliasKind(StrEnum):
    """Which address space the alias lives in."""

    SHARED = "shared"  # <local>@closetcompute.online
    SUBDOMAIN = "subdomain"  # <local>@<username>.closetcompute.online


class AliasState(StrEnum):
    """Lifecycle state; drives the KV value the edge Worker sees."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    DELETED = "deleted"
    FORGOTTEN = "forgotten"


alias_recipients = Table(
    "alias_recipients",
    Base.metadata,
    Column("alias_id", ForeignKey("aliases.id", ondelete="CASCADE"), primary_key=True),
    Column("recipient_id", ForeignKey("recipients.id", ondelete="CASCADE"), primary_key=True),
)


class Alias(UUIDPrimaryKey, Timestamps, Base):
    """An address that forwards to one or more recipients."""

    __tablename__ = "aliases"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    local_part: Mapped[str] = mapped_column(String(64))
    domain: Mapped[str] = mapped_column(String(253))
    address: Mapped[str] = mapped_column(String(320), unique=True)
    kind: Mapped[AliasKind] = mapped_column(pg_enum(AliasKind, "alias_kind"))
    state: Mapped[AliasState] = mapped_column(
        pg_enum(AliasState, "alias_state"), default=AliasState.ACTIVE, index=True
    )
    description: Mapped[str | None] = mapped_column(EncryptedString())
    reply_enabled: Mapped[bool] = mapped_column(default=True)
    forwarded_count: Mapped[int] = mapped_column(default=0)
    blocked_count: Mapped[int] = mapped_column(default=0)
    replied_count: Mapped[int] = mapped_column(default=0)
    last_used_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]

    recipients: Mapped[list[Recipient]] = relationship(secondary=alias_recipients, lazy="raise")
    labels: Mapped[list[Label]] = relationship(secondary=alias_labels, lazy="raise")
