"""End-to-end account flows: invites, login, TOTP, backup codes, password reset, CLI."""

# 1st party imports
import re
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
from mailalias.mail.outbound import FakeMailer
from mailalias.models import Recipient, User, UserRole
from mailalias.services.users import UserService

pytestmark = pytest.mark.usefixtures("relaxed_rate_limits")
PASSWORD = "correct horse battery"


def _link_token(mailer: FakeMailer, path: str) -> str:
    """Extract the token from the last emailed link of the form /<path>/<token>.

    Args:
        mailer: Fake mailer holding sent messages.
        path: Link path segment, e.g. "invite".
    Returns:
        The token.
    """
    body = mailer.sent[-1].message.get_content()
    match = re.search(rf"/{path}/([A-Za-z0-9_-]+)", body)
    assert match, "link not found in email"
    return match.group(1)


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


async def test_invite_login_totp_logout_cycle(
    client: httpx.AsyncClient, session: AsyncSession, mailer: FakeMailer
) -> None:
    """Admin invites, invitee signs up, enables TOTP, and later needs TOTP to log in.

    Args:
        client: HTTP client.
        session: Test session.
        mailer: Fake mailer.
    Returns:
        None.
    """
    await _make_admin(session)
    assert await _login(client, "boss") is False

    created = await client.post("/api/v1/admin/invites", json={"email": "Carol@Example.com"})
    assert created.status_code == 201, created.text
    assert mailer.sent[-1].rcpt_to == ["carol@example.com"]
    token = _link_token(mailer, "invite")
    await client.post("/api/v1/auth/logout")

    accepted = await client.post(
        "/api/v1/auth/invite/accept",
        json={"token": token, "username": "carol", "password": PASSWORD},
    )
    assert accepted.status_code == 201
    reused = await client.post(
        "/api/v1/auth/invite/accept",
        json={"token": token, "username": "carol2", "password": PASSWORD},
    )
    assert reused.status_code == 404

    carol = await session.scalar(select(User).where(User.username == "carol"))
    assert carol is not None
    recipient = await session.get(Recipient, carol.default_recipient_id)
    assert recipient is not None and recipient.is_usable

    assert await _login(client, "carol") is False
    me = await client.get("/api/v1/me")
    assert me.json()["email"] == "carol@example.com"

    uri = (await client.post("/api/v1/me/totp/setup")).json()["otpauth_uri"]
    secret = parse_qs(urlparse(uri).query)["secret"][0]
    enabled = await client.post("/api/v1/me/totp/enable", json={"code": pyotp.TOTP(secret).now()})
    assert enabled.status_code == 200
    assert len(enabled.json()["backup_codes"]) == 10

    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    assert (await client.get("/api/v1/me")).status_code == 401

    assert await _login(client, "carol") is True
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


async def test_login_does_not_reveal_usernames(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Unknown user and wrong password give the same error.

    Args:
        client: HTTP client.
        session: Test session.
    Returns:
        None.
    """
    await _make_admin(session)
    unknown = await client.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"})
    wrong = await client.post("/api/v1/auth/login", json={"username": "boss", "password": "x"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


async def test_password_reset_flow(
    client: httpx.AsyncClient, session: AsyncSession, mailer: FakeMailer
) -> None:
    """Reset is silent for unknown emails, works once, and revokes existing sessions.

    Args:
        client: HTTP client.
        session: Test session.
        mailer: Fake mailer.
    Returns:
        None.
    """
    await _make_admin(session)
    await _login(client, "boss")

    unknown = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "x@example.com"}
    )
    assert unknown.status_code == 202 and not mailer.sent
    known = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "BOSS@example.com"}
    )
    assert known.status_code == 202 and known.json() == unknown.json()
    token = _link_token(mailer, "reset")

    new_password = "a brand new password"
    body = {"token": token, "password": new_password}
    assert (await client.post("/api/v1/auth/password-reset/confirm", json=body)).status_code == 204
    assert (await client.post("/api/v1/auth/password-reset/confirm", json=body)).status_code == 404
    assert (await client.get("/api/v1/me")).status_code == 401  # old session revoked
    assert await _login(client, "boss", new_password) is False


async def test_non_admin_cannot_invite(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """Regular users get 403 on admin routes.

    Args:
        client: HTTP client.
        session: Test session.
    Returns:
        None.
    """
    await UserService(session).create_user("dave", "dave@example.com", PASSWORD)
    await session.commit()
    await _login(client, "dave")
    response = await client.post("/api/v1/admin/invites", json={"email": "e@example.com"})
    assert response.status_code == 403


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
                    user.default_recipient_id = None
                    await db.flush()
                    await db.execute(delete(Recipient).where(Recipient.user_id == user.id))
                    await db.execute(delete(User).where(User.id == user.id))
                    await db.commit()
                return role
        finally:
            await get_engine().dispose()

    assert asyncio.run(_check_and_cleanup()) is UserRole.ADMIN
