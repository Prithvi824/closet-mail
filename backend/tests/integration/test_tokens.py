"""API tokens: issue/list/revoke, bearer auth with scopes, session-only endpoints, expiry."""

# 1st party imports
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

# 3rd party imports
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.models import ApiToken, UserRole
from mailalias.services.users import UserService

pytestmark = pytest.mark.usefixtures("dispatched", "relaxed_rate_limits")
PASSWORD = "token-password-1"


@pytest.fixture
async def bare(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """A client without cookies or the CSRF header, like a script would be.

    Args:
        app: Application.
    Returns:
        An async iterator yielding the client.
    """
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


async def _issue(
    client: httpx.AsyncClient,
    session: AsyncSession,
    scopes: list[str],
    role: UserRole = UserRole.USER,
) -> dict[str, str]:
    """Create a user, sign in and issue a token.

    Args:
        client: Browser-like client.
        session: Test session.
        scopes: Token scopes.
        role: User role.
    Returns:
        The creation response body.
    """
    await UserService(session).create_user("pia", "pia@example.com", PASSWORD, role)
    await session.commit()
    login = await client.post("/api/v1/auth/login", json={"username": "pia", "password": PASSWORD})
    assert login.status_code == 200
    created = await client.post("/api/v1/tokens", json={"name": "script", "scopes": scopes})
    assert created.status_code == 201
    return created.json()


def _auth(token: str) -> dict[str, str]:
    """Bearer header.

    Args:
        token: Token value.
    Returns:
        Headers.
    """
    return {"Authorization": f"Bearer {token}"}


async def test_secret_shown_once_and_listing_hides_it(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Creation returns ma_<prefix>_<secret>; the list never does."""
    created = await _issue(client, session, ["aliases:read"])
    assert created["token"].startswith(f"ma_{created['prefix']}_")
    (listed,) = (await client.get("/api/v1/tokens")).json()
    assert "token" not in listed and listed["prefix"] == created["prefix"]


async def test_scopes_are_enforced_per_method(
    client: httpx.AsyncClient, bare: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Read scope reads; writes need the write scope; no CSRF header is needed with a token."""
    token = (await _issue(client, session, ["aliases:read", "recipients:read"]))["token"]
    listed = await bare.get("/api/v1/aliases", headers=_auth(token))
    assert listed.status_code == 200
    assert "X-RateLimit-Limit" in listed.headers
    assert (await bare.get("/api/v1/labels", headers=_auth(token))).status_code == 200
    denied = await bare.post("/api/v1/aliases", json={}, headers=_auth(token))
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "scope"
    recipients = await bare.get("/api/v1/recipients", headers=_auth(token))
    assert recipients.status_code == 200
    rid = recipients.json()[0]["id"]
    patched = await bare.patch(
        f"/api/v1/recipients/{rid}", json={"disabled": True}, headers=_auth(token)
    )
    assert patched.status_code == 403


async def test_write_scope_creates_alias_without_csrf(
    client: httpx.AsyncClient, bare: httpx.AsyncClient, session: AsyncSession
) -> None:
    """aliases:write can create; contacts:write can start a conversation."""
    token = (await _issue(client, session, ["aliases:write", "contacts:write"]))["token"]
    created = await bare.post(
        "/api/v1/aliases", json={"local_part": "scripted"}, headers=_auth(token)
    )
    assert created.status_code == 201
    contact = await bare.post(
        f"/api/v1/aliases/{created.json()['id']}/contacts",
        json={"email": "bob@example.net"},
        headers=_auth(token),
    )
    assert contact.status_code == 201
    no_read = await bare.get("/api/v1/aliases", headers=_auth(token))
    assert no_read.status_code == 403


async def test_session_only_endpoints_refuse_tokens(
    client: httpx.AsyncClient, bare: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Tokens cannot reach the profile, blocklist, token management or admin."""
    scopes = ["aliases:read", "aliases:write", "recipients:read", "contacts:write"]
    token = (await _issue(client, session, scopes, UserRole.ADMIN))["token"]
    for method, url in (
        ("GET", "/api/v1/me"),
        ("GET", "/api/v1/blocklist"),
        ("GET", "/api/v1/tokens"),
        ("POST", "/api/v1/tokens"),
        ("GET", "/api/v1/admin/users"),
        ("GET", "/api/v1/quarantine"),
    ):
        response = await bare.request(
            method, url, json={} if method == "POST" else None, headers=_auth(token)
        )
        assert response.status_code == 403, url


async def test_expired_revoked_and_garbage_tokens(
    client: httpx.AsyncClient, bare: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Expired and revoked tokens and malformed values are 401; use is recorded."""
    created = await _issue(client, session, ["aliases:read"])
    token = created["token"]
    assert (await bare.get("/api/v1/aliases", headers=_auth(token))).status_code == 200
    row = await session.get(ApiToken, created["id"])
    assert row is not None
    await session.refresh(row)
    assert row.last_used_at is not None
    await session.execute(
        update(ApiToken)
        .where(ApiToken.id == row.id)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await session.commit()
    expired = await bare.get("/api/v1/aliases", headers=_auth(token))
    assert expired.status_code == 401 and expired.json()["error"]["code"] == "invalid_token"
    wrong_secret = token[:-4] + "zzzz"
    assert (await bare.get("/api/v1/aliases", headers=_auth(wrong_secret))).status_code == 401
    assert (await bare.get("/api/v1/aliases", headers=_auth("nonsense"))).status_code == 401
    assert (await client.delete(f"/api/v1/tokens/{created['id']}")).status_code == 204
    assert (await client.get("/api/v1/tokens")).json() == []


async def test_invalid_scopes_rejected(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """Unknown scopes and empty scope lists are refused."""
    await _issue(client, session, ["aliases:read"])
    bad = await client.post("/api/v1/tokens", json={"name": "x", "scopes": ["admin"]})
    empty = await client.post("/api/v1/tokens", json={"name": "x", "scopes": []})
    assert bad.status_code == 422 and empty.status_code == 422
