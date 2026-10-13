"""Request/response models for authentication endpoints."""

# 1st party imports
from typing import Any, Literal

# 3rd party imports
from pydantic import BaseModel, EmailStr, Field

MfaMethod = Literal["totp", "webauthn"]


class LoginRequest(BaseModel):
    """Username/password login."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    """Whether a second factor is still needed, and which ones the user can use."""

    mfa_required: bool
    mfa_methods: list[MfaMethod]


class PasskeyOptions(BaseModel):
    """WebAuthn options for the browser (PublicKeyCredential*Options JSON)."""

    options: dict[str, Any]


class PasskeyAssertion(BaseModel):
    """The browser's PublicKeyCredential (JSON form) for a login."""

    credential: dict[str, Any]


class TotpRequest(BaseModel):
    """Second-factor code: TOTP or backup code."""

    code: str = Field(min_length=6, max_length=16)


class InviteAcceptRequest(BaseModel):
    """Redeem an invite."""

    token: str = Field(min_length=10, max_length=128)
    username: str = Field(min_length=3, max_length=30)
    password: str = Field(min_length=1, max_length=256)


class PasswordResetRequest(BaseModel):
    """Ask for a reset link."""

    email: EmailStr


class PasswordResetConfirm(BaseModel):
    """Set a new password with a reset token."""

    token: str = Field(min_length=10, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class InviteCreate(BaseModel):
    """Admin: invite an email address."""

    email: EmailStr
