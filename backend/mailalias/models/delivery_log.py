"""Delivery log: one row per message sent to one inbox, updated by provider webhooks."""

# 1st party imports
import uuid
from datetime import datetime
from enum import StrEnum

# 3rd party imports
from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

# local imports
from mailalias.models.base import Base, Timestamps, UUIDPrimaryKey, pg_enum


class DeliveryStatus(StrEnum):
    """Latest known state of one send."""

    SENT = "sent"
    DELIVERED = "delivered"
    BOUNCED = "bounced"
    COMPLAINED = "complained"
    DELAYED = "delayed"


class DeliveryLog(UUIDPrimaryKey, Timestamps, Base):
    """One send of a logged message to one inbox (recipient_id is None for replies)."""

    __tablename__ = "delivery_log"

    mail_log_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mail_log.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recipients.id", ondelete="SET NULL")
    )
    provider_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    status: Mapped[DeliveryStatus] = mapped_column(
        pg_enum(DeliveryStatus, "delivery_status"), default=DeliveryStatus.SENT
    )
    status_at: Mapped[datetime] = mapped_column(server_default=func.now())
