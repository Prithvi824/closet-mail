"""Response model for failed deliveries (bounces, complaints, delays)."""

# 1st party imports
import uuid
from datetime import datetime

# 3rd party imports
from pydantic import BaseModel

# local imports
from mailalias.models import FailedDelivery, FailureKind


class FailedDeliveryResponse(BaseModel):
    """One delivery problem as shown to the user."""

    id: uuid.UUID
    kind: FailureKind
    recipient_id: uuid.UUID | None
    recipient_email: str | None
    alias_id: uuid.UUID | None
    alias_address: str | None
    detail: str | None
    created_at: datetime

    @classmethod
    def build(
        cls, entry: FailedDelivery, recipient_email: str | None, alias_address: str | None
    ) -> "FailedDeliveryResponse":
        """Build from a row.

        Args:
            entry: Failure row.
            recipient_email, alias_address: Joined addresses, if any.
        Returns:
            The response model.
        """
        return cls(
            id=entry.id,
            kind=entry.kind,
            recipient_id=entry.recipient_id,
            recipient_email=recipient_email,
            alias_id=entry.alias_id,
            alias_address=alias_address,
            detail=entry.detail,
            created_at=entry.created_at,
        )
