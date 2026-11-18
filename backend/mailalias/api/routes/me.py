"""The signed-in operator's profile and two-factor settings."""

# 1st party imports
import json
import uuid

# 3rd party imports
from fastapi import APIRouter, status

# local imports
from mailalias.api.deps import AppSettings, CurrentSession, CurrentUser, DbSession, Sessions
from mailalias.db import get_redis
from mailalias.schemas.auth import PasskeyOptions
from mailalias.schemas.me import (
    BackupCodesResponse,
    MeResponse,
    PasskeyRegister,
    PasskeyResponse,
    PasswordConfirm,
    TotpEnableRequest,
    TotpSetupResponse,
)
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
