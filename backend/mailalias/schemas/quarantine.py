"""Response models for quarantined (suspected spam) messages."""

# 1st party imports
import uuid
from datetime import datetime

# 3rd party imports
from pydantic import BaseModel

# local imports
from mailalias.models import QuarantineItem


class QuarantineResponse(BaseModel):
    """A held message as shown to its owner."""

    id: uuid.UUID
    alias_id: uuid.UUID | None
    alias_address: str | None
    sender: str
    subject: str | None
    spam_score: float
    created_at: datetime
    expires_at: datetime

    @classmethod
    def build(cls, item: QuarantineItem, alias_address: str | None) -> "QuarantineResponse":
        """Build from a row.

        Args:
            item: Quarantine row.
            alias_address: Address of its alias, if it still exists.
        Returns:
            The response model.
        """
        return cls(
            id=item.id,
            alias_id=item.alias_id,
            alias_address=alias_address,
            sender=item.sender,
            subject=item.subject,
            spam_score=item.spam_score,
            created_at=item.created_at,
            expires_at=item.expires_at,
        )


class ReleaseResponse(BaseModel):
    """Release accepted; delivery happens in the background."""

    status: str = "queued"
