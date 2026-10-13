"""FastAPI dependencies: database session, session store and the authenticated user."""

# 1st party imports
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

# 3rd party imports
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.errors import Forbidden, Unauthorized
from mailalias.config import Settings, get_settings
from mailalias.db import get_redis, get_session
from mailalias.integrations.cloudflare_api import CloudflareApi
from mailalias.integrations.cloudflare_queue import CloudflareQueueAdmin
from mailalias.integrations.r2 import ObjectStore, R2Storage
from mailalias.mail.outbound import OutboundMailer, get_mailer
from mailalias.models import ApiToken, User, UserRole
from mailalias.security.sessions import SESSION_COOKIE, SessionData, SessionStore
from mailalias.services.api_tokens import TokenService
from mailalias.services.system_mail import SystemMailService

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

DbSession = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def get_session_store() -> SessionStore:
    """Session store bound to the shared Redis client.

    Returns:
        A SessionStore.
    """
    return SessionStore(get_redis())


Sessions = Annotated[SessionStore, Depends(get_session_store)]


def get_storage(settings: AppSettings) -> ObjectStore:
    """R2 object storage (FastAPI dependency; overridden in tests).

    Args:
        settings: Settings.
    Returns:
        The object store.
    """
    return R2Storage(settings)


Storage = Annotated[ObjectStore, Depends(get_storage)]


async def get_queue_admin(settings: AppSettings) -> AsyncIterator[CloudflareQueueAdmin]:
    """Cloudflare queue client for the admin console (FastAPI dependency; overridden in tests).

    Args:
        settings: Settings.
    Returns:
        An async iterator yielding the client; the HTTP client is closed afterwards.
    """
    api = CloudflareApi(settings)
    try:
        yield CloudflareQueueAdmin(api)
    finally:
        await api.aclose()


QueueAdmin = Annotated[CloudflareQueueAdmin, Depends(get_queue_admin)]


def get_system_mail(
    mailer: Annotated[OutboundMailer, Depends(get_mailer)], settings: AppSettings
) -> SystemMailService:
    """System mail service using the configured mailer.

    Args:
        mailer: Outbound mailer.
        settings: App settings.
    Returns:
        A SystemMailService.
    """
    return SystemMailService(mailer, settings)


SystemMail = Annotated[SystemMailService, Depends(get_system_mail)]


async def current_session(request: Request, sessions: Sessions) -> tuple[str, SessionData]:
    """Load the browser session from the cookie.

    Args:
        request: Incoming request.
        sessions: Session store.
    Returns:
        (session id, session data). Raises Unauthorized when absent or expired.
    """
    sid = request.cookies.get(SESSION_COOKIE)
    data = await sessions.get(sid) if sid else None
    if sid is None or data is None:
        raise Unauthorized("Not signed in")
    return sid, data


CurrentSession = Annotated[tuple[str, SessionData], Depends(current_session)]


@dataclass(frozen=True)
class Principal:
    """Who is calling: the user, plus the API token when the request used one."""

    user: User
    token: ApiToken | None = None


# request.state flag set by a router's token_scopes() check; tokens are refused without it.
TOKEN_SCOPE_OK = "token_scope_ok"


async def current_principal(request: Request, db: DbSession, sessions: Sessions) -> Principal:
    """Authenticate by bearer API token, else by the browser session.

    Args:
        request: Incoming request.
        db: Database session.
        sessions: Session store.
    Returns:
        The principal. Raises Unauthorized if missing, invalid, disabled, or MFA is pending.
    """
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        found = await TokenService(db).authenticate(auth[7:])
        if found is None:
            raise Unauthorized("Invalid or expired API token", code="invalid_token")
        token, user = found
        return Principal(user, token)
    _, data = await current_session(request, sessions)
    session_user = await db.get(User, uuid.UUID(data.user_id))
    if session_user is None or session_user.disabled_at is not None:
        raise Unauthorized("Not signed in")
    # Sessions start with mfa_passed=False only when the user has TOTP or passkeys.
    if not data.mfa_passed:
        raise Unauthorized("Second factor required", code="mfa_required")
    return Principal(session_user)


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


async def current_user(request: Request, principal: CurrentPrincipal) -> User:
    """The authenticated user; API tokens only pass where the router checked their scope.

    Args:
        request: Incoming request (carries the scope-check flag).
        principal: Authenticated caller.
    Returns:
        The User. Raises Forbidden for a token on a session-only endpoint.
    """
    if principal.token is not None and not getattr(request.state, TOKEN_SCOPE_OK, False):
        raise Forbidden("API tokens cannot use this endpoint", code="token_not_allowed")
    return principal.user


def token_scopes(read: str, write: str | None = None) -> Callable[..., Awaitable[None]]:
    """Router dependency letting API tokens in when they hold the scope for the method.

    Args:
        read: Scope needed for GET/HEAD.
        write: Scope needed for other methods; None means tokens may only read.
    Returns:
        The dependency.
    """

    async def check(request: Request, principal: CurrentPrincipal) -> None:
        """Verify the token's scope (browser sessions pass untouched).

        Args:
            request: Incoming request.
            principal: Authenticated caller.
        Returns:
            None. Raises Forbidden when the scope is missing.
        """
        if principal.token is None:
            return
        needed = read if request.method in SAFE_METHODS else write
        if needed is None or needed not in principal.token.scopes:
            raise Forbidden(f"This token lacks the {needed or 'required'} scope", code="scope")
        setattr(request.state, TOKEN_SCOPE_OK, True)

    return check


CurrentUser = Annotated[User, Depends(current_user)]


async def require_admin(user: CurrentUser, principal: CurrentPrincipal) -> User:
    """Restrict a route to admins signed in with a browser session (never an API token).

    Args:
        user: Authenticated user.
        principal: Caller (rejected when it is a token).
    Returns:
        The user if admin. Raises Forbidden otherwise.
    """
    if principal.token is not None or user.role != UserRole.ADMIN:
        raise Forbidden("Admin only")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
