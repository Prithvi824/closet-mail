"""Request/response models for the current user's profile and settings."""

# 1st party imports
import uuid
from datetime import datetime
from typing import Any

# 3rd party imports
from pydantic import BaseModel, ConfigDict, Field

# local imports
from mailalias.models import AliasFormat, BannerPosition, UserRole


class MeResponse(BaseModel):
    """Profile and preferences of the signed-in user."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: str
    role: UserRole
    totp_enabled: bool
    default_recipient_id: uuid.UUID | None
    banner_position: BannerPosition
    alias_format: AliasFormat
    strip_trackers: bool
    subdomain_catchall: bool
    created_at: datetime


class SettingsUpdate(BaseModel):
    """Partial preference update; omitted fields are unchanged."""

    banner_position: BannerPosition | None = None
    alias_format: AliasFormat | None = None
    strip_trackers: bool | None = None
    subdomain_catchall: bool | None = None
    default_recipient_id: uuid.UUID | None = None


class TotpSetupResponse(BaseModel):
    """Provisioning URI to render as a QR code."""

    otpauth_uri: str


class TotpEnableRequest(BaseModel):
    """Code confirming the authenticator app is set up."""

    code: str = Field(min_length=6, max_length=8)


class BackupCodesResponse(BaseModel):
    """One-time backup codes, shown once."""

    backup_codes: list[str]


class PasswordConfirm(BaseModel):
    """Re-authentication for sensitive changes."""

    password: str = Field(min_length=1, max_length=256)


class InviteResponse(BaseModel):
    """Admin view of an invite (email shown; it is the admin's own data)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    expires_at: datetime
    used_at: datetime | None
    created_at: datetime


class PasskeyRegister(BaseModel):
    """Finish registering a passkey."""

    name: str = Field(min_length=1, max_length=60)
    credential: dict[str, Any]


class PasskeyResponse(BaseModel):
    """A registered passkey."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None
