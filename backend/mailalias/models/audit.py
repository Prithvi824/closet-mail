"""Security audit log (logins, MFA changes, invites, resets, admin actions)."""

# 1st party imports
import uuid

# 3rd party imports
from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

# local imports
from mailalias.models.base import Base, Timestamps, UUIDPrimaryKey


class AuditLog(UUIDPrimaryKey, Timestamps, Base):
    """One security-relevant event. `user_id` is the subject, `actor_id` who did it."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
