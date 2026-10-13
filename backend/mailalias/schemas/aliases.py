"""Request/response models for aliases."""

# 1st party imports
import uuid
from datetime import datetime
from typing import Literal

# 3rd party imports
from pydantic import BaseModel, Field

# local imports
from mailalias.models import Alias, AliasFormat, AliasKind, AliasState


class AliasCreate(BaseModel):
    """Create an alias; omit local_part for a generated one."""

    format: AliasFormat | None = None
    local_part: str | None = Field(default=None, max_length=64)
    subdomain: bool = False
    description: str | None = Field(default=None, max_length=500)
    recipient_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    label_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class AliasUpdate(BaseModel):
    """Partial update; omitted fields are unchanged. description=null clears it."""

    description: str | None = Field(default=None, max_length=500)
    reply_enabled: bool | None = None
    active: bool | None = None
    recipient_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)
    label_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)


class AliasBulk(BaseModel):
    """Bulk state change."""

    ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    action: Literal["activate", "deactivate", "delete"]


class AliasResponse(BaseModel):
    """An alias as shown in the dashboard."""

    id: uuid.UUID
    address: str
    local_part: str
    domain: str
    kind: AliasKind
    state: AliasState
    description: str | None
    reply_enabled: bool
    recipient_ids: list[uuid.UUID]
    label_ids: list[uuid.UUID]
    forwarded_count: int
    blocked_count: int
    replied_count: int
    last_used_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime

    @classmethod
    def build(cls, alias: Alias) -> "AliasResponse":
        """Map a model (with recipients and labels loaded) to the response.

        Args:
            alias: Alias row.
        Returns:
            The response model.
        """
        return cls(
            id=alias.id,
            address=alias.address,
            local_part=alias.local_part,
            domain=alias.domain,
            kind=alias.kind,
            state=alias.state,
            description=alias.description,
            reply_enabled=alias.reply_enabled,
            recipient_ids=[r.id for r in alias.recipients],
            label_ids=[label.id for label in alias.labels],
            forwarded_count=alias.forwarded_count,
            blocked_count=alias.blocked_count,
            replied_count=alias.replied_count,
            last_used_at=alias.last_used_at,
            deleted_at=alias.deleted_at,
            created_at=alias.created_at,
        )


class AliasPage(BaseModel):
    """One page of search results."""

    items: list[AliasResponse]
    total: int
    page: int
    per_page: int
