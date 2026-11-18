"""Operator account flows: login, TOTP, backup codes, operator-only access, CLI."""

# 1st party imports
import secrets
from urllib.parse import parse_qs, urlparse

# 3rd party imports
import httpx
import pyotp
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from typer.testing import CliRunner

# local imports
from mailalias.cli import app as cli_app
from mailalias.db import get_redis
from mailalias.models import Recipient, User, UserRole
from mailalias.security.sessions import SESSION_COOKIE, SessionStore
from mailalias.services.users import MFA_MAX_FAILURES, UserService
from tests.integration.harness import default_inbox

pytestmark = pytest.mark.usefixtures("relaxed_rate_limits")
PASSWORD = "correct horse battery"


async def _make_admin(session: AsyncSession) -> User:
    """Create an admin directly through the service.

    Args:
        session: Test session.
    Returns:
        The admin user.
    """
    admin = await UserService(session).create_user(
        "boss", "boss@example.com", PASSWORD, UserRole.ADMIN
    )
    await session.commit()
    return admin


async def _login(client: httpx.AsyncClient, username: str, password: str = PASSWORD) -> bool:
    """Log in and return whether a second factor is required.

    Args:
        client: HTTP client (keeps cookies).
        username: Username.
        password: Password.
    Returns:
        Whether a second factor is required.
    """
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return bool(response.json()["mfa_required"])


async def test_login_totp_logout_cycle(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """The operator signs in, enables TOTP, and later needs TOTP to sign in.

    Args:
        client: HTTP client.
        session: Test session.
    Returns:
        None.
    """
    admin = await _make_admin(session)
    recipient = await default_inbox(session, admin)
    assert recipient.is_usable and recipient.forward_by_default

    assert await _login(client, "boss") is False
    me = await client.get("/api/v1/me")
    assert me.json()["email"] == "boss@example.com"

    uri = (await client.post("/api/v1/me/totp/setup")).json()["otpauth_uri"]
    secret = parse_qs(urlparse(uri).query)["secret"][0]
    enabled = await client.post("/api/v1/me/totp/enable", json={"code": pyotp.TOTP(secret).now()})
    assert enabled.status_code == 200
    assert len(enabled.json()["backup_codes"]) == 10

    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    assert (await client.get("/api/v1/me")).status_code == 401

    assert await _login(client, "boss") is True
    pending = await client.get("/api/v1/me")
    assert pending.status_code == 401 and pending.json()["error"]["code"] == "mfa_required"
    wrong = await client.post("/api/v1/auth/totp", json={"code": "000000"})
    assert wrong.status_code == 401
    ok = await client.post("/api/v1/auth/totp", json={"code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 204
    assert (await client.get("/api/v1/me")).status_code == 200


async def test_backup_code_works_once(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """A backup code completes login once and is rejected the second time.

    Args:
        client: HTTP client.
        session: Test session.
    Returns:
        None.
    """
    await _make_admin(session)
    await _login(client, "boss")
    uri = (await client.post("/api/v1/me/totp/setup")).json()["otpauth_uri"]
    secret = parse_qs(urlparse(uri).query)["secret"][0]
    codes = (
        await client.post("/api/v1/me/totp/enable", json={"code": pyotp.TOTP(secret).now()})
    ).json()["backup_codes"]

    for expected in (204, 401):
        await client.post("/api/v1/auth/logout")
        assert await _login(client, "boss") is True
        response = await client.post("/api/v1/auth/totp", json={"code": codes[0]})
        assert response.status_code == expected


async def test_wrong_codes_lock_mfa(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """After the wrong-code limit even a valid code is refused and the session is dropped.

    Args:
        client: HTTP client.
        session: Test session.
    Returns:
        None.
    """
    await _make_admin(session)
    await _login(client, "boss")
    uri = (await client.post("/api/v1/me/totp/setup")).json()["otpauth_uri"]
    secret = parse_qs(urlparse(uri).query)["secret"][0]
    await client.post("/api/v1/me/totp/enable", json={"code": pyotp.TOTP(secret).now()})
    await client.post("/api/v1/auth/logout")
    assert await _login(client, "boss") is True
    for _ in range(MFA_MAX_FAILURES):
        wrong = await client.post("/api/v1/auth/totp", json={"code": "000000"})
        assert wrong.status_code == 401
    locked = await client.post("/api/v1/auth/totp", json={"code": pyotp.TOTP(secret).now()})
    assert locked.status_code == 429 and locked.json()["error"]["code"] == "mfa_locked"
    assert (await client.get("/api/v1/me")).status_code == 401


async def test_login_does_not_reveal_usernames_or_roles(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Unknown user, wrong password and a non-operator's correct password look the same.

    Args:
        client: HTTP client.
        session: Test session.
    Returns:
        None.
    """
    await _make_admin(session)
    await UserService(session).create_user("dave", "dave@example.com", PASSWORD)
    await session.commit()
    unknown = await client.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"})
    wrong = await client.post("/api/v1/auth/login", json={"username": "boss", "password": "x"})
    not_operator = await client.post(
        "/api/v1/auth/login", json={"username": "dave", "password": PASSWORD}
    )
    assert unknown.status_code == wrong.status_code == not_operator.status_code == 401
    assert unknown.json() == wrong.json() == not_operator.json()


async def test_existing_non_operator_session_is_refused(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """A session left over from before the lockdown no longer works for a non-operator.

    Args:
        client: HTTP client.
        session: Test session.
    Returns:
        None.
    """
    dave = await UserService(session).create_user("dave", "dave@example.com", PASSWORD)
    await session.commit()
    sid = await SessionStore(get_redis()).create(dave.id, mfa_passed=True)
    client.cookies.set(SESSION_COOKIE, sid)
    response = await client.get("/api/v1/me")
    assert response.status_code == 401


async def test_invite_and_reset_endpoints_are_gone(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Self-service sign-up and password reset no longer exist.

    Args:
        client: HTTP client.
        session: Test session.
    Returns:
        None.
    """
    await _make_admin(session)
    await _login(client, "boss")
    for method, url in (
        ("POST", "/api/v1/auth/invite/accept"),
        ("POST", "/api/v1/auth/password-reset/request"),
        ("POST", "/api/v1/auth/password-reset/confirm"),
        ("GET", "/api/v1/admin/invites"),
        ("POST", "/api/v1/admin/invites"),
    ):
        response = await client.request(method, url, json={})
        assert response.status_code in (404, 405), url


@pytest.mark.parametrize("username", ["ab", "rp", "-bad", "Has Space", "admin"])
async def test_invalid_usernames_rejected(session: AsyncSession, username: str) -> None:
    """Short, reserved or malformed usernames are refused.

    Args:
        session: Test session.
        username: Candidate username.
    Returns:
        None.
    """
    from mailalias.api.errors import ValidationFailed

    with pytest.raises(ValidationFailed):
        await UserService(session).create_user(
            username, f"{secrets.token_hex(4)}@example.com", PASSWORD
        )


def test_cli_create_admin(migrated_db: str) -> None:
    """`mailalias create-admin` creates an admin (committed, then cleaned up).

    Args:
        migrated_db: Ensures the test database exists.
    Returns:
        None.
    """
    import asyncio

    from mailalias.db import get_engine, get_session_factory

    username = f"cli-{secrets.token_hex(3)}"
    result = CliRunner().invoke(
        cli_app,
        ["create-admin", "--username", username, "--email", f"{username}@example.com"],
        input=f"{PASSWORD}\n{PASSWORD}\n",
    )
    assert result.exit_code == 0, result.output
    assert f"admin '{username}' created" in result.output

    async def _check_and_cleanup() -> UserRole | None:
        try:
            async with get_session_factory()() as db:
                user = await db.scalar(select(User).where(User.username == username))
                role = user.role if user else None
                if user:
                    await db.execute(delete(Recipient).where(Recipient.user_id == user.id))
                    await db.execute(delete(User).where(User.id == user.id))
                    await db.commit()
                return role
        finally:
            await get_engine().dispose()

    assert asyncio.run(_check_and_cleanup()) is UserRole.ADMIN


def _cli_user(username: str, role: UserRole) -> None:
    """Create a committed user outside the test transaction (the CLI uses its own sessions).

    Args:
        username: Username.
        role: Role.
    Returns:
        None.
    """
    import asyncio

    from mailalias.db import get_engine, get_session_factory

    async def _create() -> None:
        try:
            async with get_session_factory()() as db:
                await UserService(db).create_user(
                    username, f"{username}@example.com", PASSWORD, role
                )
                await db.commit()
        finally:
            await get_engine().dispose()

    asyncio.run(_create())


def _cli_cleanup(username: str, password: str) -> bool:
    """Check a password through the service, then delete the user.

    Args:
        username: Username.
        password: Password to check.
    Returns:
        Whether the password authenticates.
    """
    import asyncio

    from mailalias.db import get_engine, get_session_factory

    async def _run() -> bool:
        try:
            async with get_session_factory()() as db:
                ok = await UserService(db).authenticate(username, password) is not None
                user = await db.scalar(select(User).where(User.username == username))
                if user:
                    await db.execute(delete(Recipient).where(Recipient.user_id == user.id))
                    await db.execute(delete(User).where(User.id == user.id))
                    await db.commit()
                return ok
        finally:
            await get_engine().dispose()

    return asyncio.run(_run())


def test_cli_reset_password(migrated_db: str) -> None:
    """`mailalias reset-password` sets a new operator password; other accounts are refused.

    Args:
        migrated_db: Ensures the test database exists.
    Returns:
        None.
    """
    operator, other = f"op-{secrets.token_hex(3)}", f"sub-{secrets.token_hex(3)}"
    _cli_user(operator, UserRole.ADMIN)
    _cli_user(other, UserRole.USER)
    new_password = "a brand new password"
    try:
        result = CliRunner().invoke(
            cli_app,
            ["reset-password", "--username", operator],
            input=f"{new_password}\n{new_password}\n",
        )
        refused = CliRunner().invoke(
            cli_app,
            ["reset-password", "--username", other],
            input=f"{new_password}\n{new_password}\n",
        )
    finally:
        operator_ok = _cli_cleanup(operator, new_password)
        _cli_cleanup(other, PASSWORD)
    assert result.exit_code == 0, result.output
    assert refused.exit_code == 1
    assert operator_ok is True
