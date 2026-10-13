"""The signed-in user's profile, preferences and two-factor settings."""

# 1st party imports
import json
import uuid

# 3rd party imports
from fastapi import APIRouter, Query, status
from sqlalchemy import select

# local imports
from mailalias.api.deps import AppSettings, CurrentSession, CurrentUser, DbSession, Sessions
from mailalias.api.errors import ValidationFailed
from mailalias.db import get_redis
from mailalias.models import Recipient
from mailalias.schemas.activity import ActivityResponse
from mailalias.schemas.auth import PasskeyOptions
from mailalias.schemas.me import (
    BackupCodesResponse,
    MeResponse,
    PasskeyRegister,
    PasskeyResponse,
    PasswordConfirm,
    SettingsUpdate,
    TotpEnableRequest,
    TotpSetupResponse,
)
from mailalias.services import activity, kv_sync
from mailalias.services.passkeys import PasskeyService
from mailalias.services.users import UserService

router = APIRouter(prefix="/me", tags=["me"])


@router.get("")
async def get_me(user: CurrentUser) -> MeResponse:
    """Return the current user's profile.

    Args:
        user: Authenticated user.
    Returns:
        Profile and preferences.
    """
    return MeResponse.model_validate(user)


@router.get("/activity")
async def get_activity(
    user: CurrentUser, db: DbSession, days: int = Query(default=30, ge=1, le=90)
) -> ActivityResponse:
    """Daily totals for the last `days` days and the last 100 handled messages.

    Args:
        user, db: Request dependencies.
        days: Window for the daily totals (1-90).
    Returns:
        The activity summary (no correspondent addresses or subjects).
    """
    daily = await activity.daily_totals(db, user, days)
    return ActivityResponse.build(daily, await activity.recent_mail(db, user))


@router.patch("/settings")
async def update_settings(body: SettingsUpdate, user: CurrentUser, db: DbSession) -> MeResponse:
    """Update preferences; only fields present in the body change.

    Args:
        body: Partial settings.
        user: Authenticated user.
        db: Database session.
    Returns:
        The updated profile.
    """
    changes = body.model_dump(exclude_unset=True)
    if "default_recipient_id" in changes:
        recipient = await db.scalar(
            select(Recipient).where(
                Recipient.id == changes["default_recipient_id"], Recipient.user_id == user.id
            )
        )
        if recipient is None or not recipient.is_usable:
            raise ValidationFailed("Default recipient must be one of your verified recipients")
    for field, value in changes.items():
        if value is not None:
            setattr(user, field, value)
    if "subdomain_catchall" in changes:
        kv_sync.mark_subdomain(db, user.id)
    await db.commit()
    return MeResponse.model_validate(user)


@router.post("/totp/setup")
async def totp_setup(user: CurrentUser, db: DbSession) -> TotpSetupResponse:
    """Start TOTP enrolment.

    Args:
        user: Authenticated user.
        db: Database session.
    Returns:
        The otpauth URI for the QR code.
    """
    uri = await UserService(db).begin_totp_setup(user)
    await db.commit()
    return TotpSetupResponse(otpauth_uri=uri)


@router.post("/totp/enable")
async def totp_enable(
    body: TotpEnableRequest,
    user: CurrentUser,
    session: CurrentSession,
    db: DbSession,
    sessions: Sessions,
) -> BackupCodesResponse:
    """Confirm TOTP enrolment; the current session counts as MFA-passed.

    Args:
        body: Code from the authenticator.
        user: Authenticated user.
        session: Current session.
        db: Database session.
        sessions: Session store.
    Returns:
        Backup codes (shown once).
    """
    codes = await UserService(db).enable_totp(user, body.code)
    await db.commit()
    sid, data = session
    data.mfa_passed = True
    await sessions.save(sid, data)
    return BackupCodesResponse(backup_codes=codes)


@router.delete("/totp", status_code=status.HTTP_204_NO_CONTENT)
async def totp_disable(body: PasswordConfirm, user: CurrentUser, db: DbSession) -> None:
    """Turn off TOTP (requires the password).

    Args:
        body: Current password.
        user: Authenticated user.
        db: Database session.
    Returns:
        None (204).
    """
    await UserService(db, get_redis()).disable_totp(user, body.password)
    await db.commit()


@router.get("/webauthn")
async def list_passkeys(
    user: CurrentUser, db: DbSession, sessions: Sessions, settings: AppSettings
) -> list[PasskeyResponse]:
    """List registered passkeys.

    Args:
        user, db, sessions, settings: Request dependencies.
    Returns:
        Passkeys, oldest first.
    """
    credentials = await PasskeyService(db, settings, sessions).list(user)
    return [PasskeyResponse.model_validate(credential) for credential in credentials]


@router.post("/webauthn/register/begin")
async def passkey_register_begin(
    user: CurrentUser,
    session: CurrentSession,
    db: DbSession,
    sessions: Sessions,
    settings: AppSettings,
) -> PasskeyOptions:
    """Start registering a passkey.

    Args:
        user, session, db, sessions, settings: Request dependencies.
    Returns:
        WebAuthn creation options.
    """
    sid, data = session
    options = await PasskeyService(db, settings, sessions).begin_registration(user, sid, data)
    return PasskeyOptions(options=json.loads(options))


@router.post("/webauthn/register/finish", status_code=status.HTTP_201_CREATED)
async def passkey_register_finish(
    body: PasskeyRegister,
    user: CurrentUser,
    session: CurrentSession,
    db: DbSession,
    sessions: Sessions,
    settings: AppSettings,
) -> PasskeyResponse:
    """Verify and store a new passkey.

    Args:
        body: Name and the browser's credential JSON.
        user, session, db, sessions, settings: Request dependencies.
    Returns:
        The stored passkey.
    """
    sid, data = session
    credential = await PasskeyService(db, settings, sessions).finish_registration(
        user, sid, data, body.name, json.dumps(body.credential)
    )
    await db.commit()
    return PasskeyResponse.model_validate(credential)


@router.delete("/webauthn/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_passkey(
    credential_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    sessions: Sessions,
    settings: AppSettings,
) -> None:
    """Remove a passkey.

    Args:
        credential_id: Passkey id.
        user, db, sessions, settings: Request dependencies.
    Returns:
        None (204).
    """
    await PasskeyService(db, settings, sessions).delete(user, credential_id)
    await db.commit()
