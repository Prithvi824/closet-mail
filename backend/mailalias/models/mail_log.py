"""Mail log: one row per handled message. Never stores subjects; the sender domain is encrypted."""

# 1st party imports
import uuid
from datetime import datetime

# 3rd party imports
from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

# local imports
from mailalias.mail.types import MailKind, Outcome
from mailalias.models.base import Base, Timestamps, UUIDPrimaryKey, pg_enum
from mailalias.security.crypto import EncryptedString


class MailLog(UUIDPrimaryKey, Timestamps, Base):
    """Metadata about one processed message."""

    __tablename__ = "mail_log"
    __table_args__ = (
        Index("ix_mail_log_user_created", "user_id", "created_at"),
        Index("ix_mail_log_user_received", "user_id", "received_at"),
        Index("ix_mail_log_created_at", "created_at"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    alias_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("aliases.id", ondelete="SET NULL")
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL")
    )
    kind: Mapped[MailKind] = mapped_column(pg_enum(MailKind, "mail_kind"))
    outcome: Mapped[Outcome] = mapped_column(pg_enum(Outcome, "mail_outcome"))
    reason: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(default=0)
    spam_score: Mapped[float | None]
    provider_id: Mapped[str | None] = mapped_column(String(128), index=True)
    # When the edge accepted the message; usage is bucketed by this, not by processing time.
    received_at: Mapped[datetime | None]
    sender_domain_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    sender_domain: Mapped[str | None] = mapped_column(EncryptedString())
