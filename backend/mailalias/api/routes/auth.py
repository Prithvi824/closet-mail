"""Authentication: login, second factor, logout, invites and password reset."""

# 1st party imports
import json
import uuid

# 3rd party imports
from fastapi import APIRouter, Request, Response, status

# local imports
from mailalias.api.deps import AppSettings, CurrentSession, DbSession, Sessions, SystemMail
from mailalias.api.errors import Unauthorized
from mailalias.config import Settings
from mailalias.db import get_redis
from mailalias.models import User
from mailalias.schemas.auth import (
    InviteAcceptRequest,
    LoginRequest,
    LoginResponse,
    MfaMethod,
    PasskeyAssertion,
    PasskeyOptions,
    PasswordResetConfirm,
    PasswordResetRequest,
    TotpRequest,
)
from mailalias.security.sessions import SESSION_COOKIE, SESSION_TTL_SECONDS, SessionData
from mailalias.services import audit
from mailalias.services.invites import InviteService
from mailalias.services.passkeys import PasskeyService, has_passkeys
from mailalias.services.users import UserService

router = APIRouter(prefix="/auth", tags=["auth"])


def set_session_cookie(response: Response, sid: str, settings: Settings) -> None:
    """Attach the session cookie.

    Args:
        response: Outgoing response.
        sid: Session id.
        settings: Decides the Secure flag (prod only).
    Returns:
        None.
    """
    response.set_cookie(
        SESSION_COOKIE,
        sid,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.is_prod,
        samesite="lax",
        path="/",
    )


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    sessions: Sessions,
    settings: AppSettings,
) -> LoginResponse:
    """Check credentials and start a (possibly MFA-pending) session.

    Args:
        body: Credentials.
        request: Incoming request (old session cookie is revoked).
        response: Response receiving the new cookie.
        db: Database session.
        sessions: Session store.
        settings: App settings.
    Returns:
        Whether a second factor is required next, and which methods are available.
    """
    user = await UserService(db, get_redis()).authenticate(body.username, body.password)
    if user is None:
        await audit.record(db, "login.failed")
        await db.commit()
        raise Unauthorized("Invalid username or password", code="invalid_credentials")
    if old_sid := request.cookies.get(SESSION_COOKIE):
        await sessions.delete(old_sid)
    methods: list[MfaMethod] = ["totp"] if user.totp_enabled else []
    if await has_passkeys(db, user.id):
        methods.append("webauthn")
    sid = await sessions.create(user.id, mfa_passed=not methods)
    await audit.record(db, "login.password_ok", user_id=user.id)
    await db.commit()
    set_session_cookie(response, sid, settings)
    return LoginResponse(mfa_required=bool(methods), mfa_methods=methods)


@router.post("/totp", status_code=status.HTTP_204_NO_CONTENT)
async def submit_totp(
    body: TotpRequest, session: CurrentSession, db: DbSession, sessions: Sessions
) -> None:
    """Complete login with a TOTP or backup code.

    Args:
        body: The code.
        session: MFA-pending session.
        db: Database session.
        sessions: Session store.
    Returns:
        None (204). Raises Unauthorized for a wrong code.
    """
    sid, data = session
    user = await db.get(User, uuid.UUID(data.user_id))
    if user is None or not user.totp_enabled:
        raise Unauthorized("Not signed in")
    if not await UserService(db, get_redis()).verify_second_factor(user, body.code):
        await audit.record(db, "login.mfa_failed", user_id=user.id)
        await db.commit()
        raise Unauthorized("Invalid code", code="invalid_code")
    data.mfa_passed = True
    await sessions.save(sid, data)
    await audit.record(db, "login.success", user_id=user.id)
    await db.commit()


async def _pending_user(db: DbSession, session: tuple[str, SessionData]) -> User:
    """The user of an MFA-pending (or complete) session.

    Args:
        db: Database session.
        session: (sid, data).
    Returns:
        The user. Raises Unauthorized when missing or disabled.
    """
    user = await db.get(User, uuid.UUID(session[1].user_id))
    if user is None or user.disabled_at is not None:
        raise Unauthorized("Not signed in")
    return user


@router.post("/webauthn/begin")
async def passkey_login_begin(
    session: CurrentSession, db: DbSession, sessions: Sessions, settings: AppSettings
) -> PasskeyOptions:
    """Start the passkey step of a login.

    Args:
        session: MFA-pending session.
        db, sessions, settings: Request dependencies.
    Returns:
        WebAuthn request options.
    """
    user = await _pending_user(db, session)
    sid, data = session
    options = await PasskeyService(db, settings, sessions).begin_authentication(user, sid, data)
    return PasskeyOptions(options=json.loads(options))


@router.post("/webauthn/finish", status_code=status.HTTP_204_NO_CONTENT)
async def passkey_login_finish(
    body: PasskeyAssertion,
    session: CurrentSession,
    db: DbSession,
    sessions: Sessions,
    settings: AppSettings,
) -> None:
    """Complete login with a passkey assertion.

    Args:
        body: Browser credential JSON.
        session: MFA-pending session.
        db, sessions, settings: Request dependencies.
    Returns:
        None (204). Raises Unauthorized when verification fails.
    """
    user = await _pending_user(db, session)
    sid, data = session
    service = PasskeyService(db, settings, sessions)
    try:
        await service.finish_authentication(user, sid, data, json.dumps(body.credential))
    finally:
        await db.commit()


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, sessions: Sessions) -> None:
    """End the current session (idempotent).

    Args:
        request: Incoming request.
        response: Response clearing the cookie.
        sessions: Session store.
    Returns:
        None (204).
    """
    if sid := request.cookies.get(SESSION_COOKIE):
        await sessions.delete(sid)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.post("/invite/accept", status_code=status.HTTP_201_CREATED)
async def accept_invite(body: InviteAcceptRequest, db: DbSession) -> dict[str, str]:
    """Create an account from an invite.

    Args:
        body: Token and chosen credentials.
        db: Database session.
    Returns:
        {"username": ...}; the user then signs in normally.
    """
    user = await InviteService(db).accept(body.token, body.username, body.password)
    await db.commit()
    return {"username": user.username}


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
    body: PasswordResetRequest, db: DbSession, mail: SystemMail
) -> dict[str, str]:
    """Send a reset link if the email belongs to an account; same response either way.

    Args:
        body: Account email.
        db: Database session.
        mail: System mail service.
    Returns:
        A generic acknowledgement.
    """
    await UserService(db, get_redis()).request_password_reset(str(body.email), mail)
    await db.commit()
    return {"status": "If the address has an account, a reset link has been sent."}


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(
    body: PasswordResetConfirm, db: DbSession, sessions: Sessions
) -> None:
    """Set a new password and sign out every session of that user.

    Args:
        body: Token and new password.
        db: Database session.
        sessions: Session store.
    Returns:
        None (204).
    """
    user = await UserService(db, get_redis()).confirm_password_reset(body.token, body.password)
    await db.commit()
    await sessions.delete_all_for_user(user.id)
