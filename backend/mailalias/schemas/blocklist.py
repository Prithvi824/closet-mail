"""Request/response models for the sender blocklist."""

# 1st party imports
import uuid
from datetime import datetime

# 3rd party imports
from pydantic import BaseModel, Field

# local imports
from mailalias.models import BlockKind, BlocklistEntry


class BlocklistCreate(BaseModel):
    """Block an address ("spam@example.com") or a domain ("example.com")."""

    pattern: str = Field(min_length=3, max_length=320)


class BlocklistResponse(BaseModel):
    """One blocklist entry."""

    id: uuid.UUID
    pattern: str
    kind: BlockKind
    created_at: datetime

    @classmethod
    def build(cls, entry: BlocklistEntry) -> "BlocklistResponse":
        """Build from a row.

        Args:
            entry: Blocklist row.
        Returns:
            The response model.
        """
        return cls(id=entry.id, pattern=entry.pattern, kind=entry.kind, created_at=entry.created_at)
