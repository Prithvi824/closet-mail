"""Mail log: one row per handled message. Never stores subjects or addresses."""

# 1st party imports
import uuid

# 3rd party imports
from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

# local imports
from mailalias.mail.types import MailKind, Outcome
from mailalias.models.base import Base, Timestamps, UUIDPrimaryKey, pg_enum


class MailLog(UUIDPrimaryKey, Timestamps, Base):
    """Metadata about one processed message."""

    __tablename__ = "mail_log"
    __table_args__ = (Index("ix_mail_log_user_created", "user_id", "created_at"),)

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
