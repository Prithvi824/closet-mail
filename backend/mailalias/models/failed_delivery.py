"""Failed deliveries: bounces, complaints and delays reported by Resend or DSNs."""

# 1st party imports
import uuid
from enum import StrEnum

# 3rd party imports
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

# local imports
from mailalias.models.base import Base, Timestamps, UUIDPrimaryKey, pg_enum
from mailalias.security.crypto import EncryptedString


class FailureKind(StrEnum):
    """Type of delivery problem."""

    HARD = "hard"
    SOFT = "soft"
    COMPLAINT = "complaint"
    DELAYED = "delayed"
    SUPPRESSED = "suppressed"


class FailedDelivery(UUIDPrimaryKey, Timestamps, Base):
    """One delivery problem; `provider_event_id` de-duplicates webhook retries."""

    __tablename__ = "failed_deliveries"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recipients.id", ondelete="SET NULL")
    )
    alias_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("aliases.id", ondelete="SET NULL")
    )
    kind: Mapped[FailureKind] = mapped_column(pg_enum(FailureKind, "failure_kind"))
    provider_event_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    detail: Mapped[str | None] = mapped_column(EncryptedString())
