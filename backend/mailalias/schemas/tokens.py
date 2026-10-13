"""Request/response models for personal API tokens."""

# 1st party imports
import uuid
from datetime import datetime
from typing import Literal

# 3rd party imports
from pydantic import BaseModel, Field

# local imports
from mailalias.models import ApiToken

Scope = Literal["aliases:read", "aliases:write", "recipients:read", "contacts:write"]


class TokenCreate(BaseModel):
    """A new token: a label, its scopes and an optional lifetime."""

    name: str = Field(min_length=1, max_length=60)
    scopes: list[Scope] = Field(min_length=1, max_length=4)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class TokenResponse(BaseModel):
    """A token as listed (the secret is never returned again)."""

    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime

    @classmethod
    def build(cls, token: ApiToken) -> "TokenResponse":
        """Build from a row.

        Args:
            token: Token row.
        Returns:
            The response model.
        """
        return cls(
            id=token.id,
            name=token.name,
            prefix=token.prefix,
            scopes=list(token.scopes),
            last_used_at=token.last_used_at,
            expires_at=token.expires_at,
            created_at=token.created_at,
        )


class TokenCreated(TokenResponse):
    """Returned once at creation: includes the full token value."""

    token: str
