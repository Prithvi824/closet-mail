"""Request/response models for recipients."""

# 1st party imports
import uuid
from datetime import datetime

# 3rd party imports
from pydantic import BaseModel, EmailStr, Field

# local imports
from mailalias.models import Recipient


class RecipientCreate(BaseModel):
    """Add a forwarding destination."""

    email: EmailStr


class RecipientUpdate(BaseModel):
    """Enable or disable a recipient."""

    disabled: bool


class PgpKeyUpdate(BaseModel):
    """Set (or clear with null) a recipient's PGP key."""

    public_key: str | None = Field(default=None, max_length=64 * 1024)
    protect_subject: bool = False


class RecipientResponse(BaseModel):
    """A recipient as shown in the dashboard."""

    id: uuid.UUID
    email: str
    verified: bool
    disabled: bool
    is_default: bool
    pgp_fingerprint: str | None
    pgp_protect_subject: bool
    created_at: datetime

    @classmethod
    def build(cls, recipient: Recipient, default_id: uuid.UUID | None) -> "RecipientResponse":
        """Map a model to the response.

        Args:
            recipient: Recipient row.
            default_id: The owner's default recipient id.
        Returns:
            The response model.
        """
        return cls(
            id=recipient.id,
            email=recipient.email,
            verified=recipient.verified_at is not None,
            disabled=recipient.disabled_at is not None,
            is_default=recipient.id == default_id,
            pgp_fingerprint=recipient.pgp_fingerprint,
            pgp_protect_subject=recipient.pgp_protect_subject,
            created_at=recipient.created_at,
        )
