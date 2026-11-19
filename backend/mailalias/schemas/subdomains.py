"""Request/response models for operator subdomain management."""

# 1st party imports
import uuid
from datetime import datetime

# 3rd party imports
from pydantic import BaseModel, EmailStr, Field

# local imports
from mailalias.models import SubdomainState


class SubdomainCreate(BaseModel):
    """Create a subdomain with its first inbox (sent a verification link)."""

    label: str = Field(min_length=1, max_length=30)
    display_name: str | None = Field(default=None, max_length=80)
    inbox_email: EmailStr
    notes: str | None = Field(default=None, max_length=2000)


class SubdomainUpdate(BaseModel):
    """Partial update; `clear_limits` resets every limit to the defaults."""

    display_name: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)
    suspended: bool | None = None
    limits: dict[str, int] | None = None
    clear_limits: bool = False


class SubdomainStatusOut(BaseModel):
    """Latest routing check of a subdomain; null values were not checked or could not be read."""

    state: SubdomainState
    mx_ok: bool | None
    spf_ok: bool | None
    kv_ok: bool | None
    detail: str | None
    checked_at: datetime | None
    last_mail_at: datetime | None


class SubdomainResponse(BaseModel):
    """A subdomain as the operator sees it."""

    id: uuid.UUID
    label: str
    domain: str
    display_name: str | None
    notes: str | None
    is_operator: bool
    suspended: bool
    retired: bool
    catchall: bool
    inbox_count: int
    default_inbox_count: int
    alias_count: int
    received_today: int
    sends_today: int
    send_share: int
    limits: dict[str, int] | None
    status: SubdomainStatusOut
    created_at: datetime
