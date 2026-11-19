"""Operator subdomain management: create, suspend, retire, limits and the list view."""

# 1st party imports
from typing import Any

# 3rd party imports
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.config import get_settings
from mailalias.mail.outbound import FakeMailer
from mailalias.mail.types import Outcome
from mailalias.models import AliasState, MailLog, Recipient, User, UserRole
from mailalias.services.aliases import AliasService
from mailalias.services.users import UserService
from tests.integration.harness import default_inbox, make_harness, sub

pytestmark = pytest.mark.usefixtures("relaxed_rate_limits")
PASSWORD = "correct horse battery"
API = "/api/v1/operator/subdomains"


async def _operator(client: httpx.AsyncClient, session: AsyncSession) -> User:
    """Create and sign in the operator "boss".

    Args:
        client: HTTP client.
        session: Test session.
    Returns:
        The operator.
    """
    operator = await UserService(session).create_user(
        "boss", "boss@example.com", PASSWORD, UserRole.ADMIN
    )
    await session.commit()
    login = await client.post("/api/v1/auth/login", json={"username": "boss", "password": PASSWORD})
    assert login.status_code == 200
    return operator


async def _create(client: httpx.AsyncClient, label: str = "acme") -> dict[str, Any]:
    """Create a subdomain through the API.

    Args:
        client: Operator client.
        label: Label.
    Returns:
        The response body.
    """
    response = await client.post(
        API,
        json={"label": label, "display_name": "Acme Ltd", "inbox_email": f"owner@{label}.example"},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def test_create_sends_verification_and_flags_the_first_inbox(
    client: httpx.AsyncClient,
    session: AsyncSession,
    mailer: FakeMailer,
    dispatched: list[tuple[str, str]],
) -> None:
    """A new subdomain has no login, one unverified default inbox, and catch-all on."""
    await _operator(client, session)
    body = await _create(client)
    assert (body["label"], body["domain"]) == ("acme", "acme.closetcompute.online")
    assert (body["display_name"], body["is_operator"], body["catchall"]) == (
        "Acme Ltd",
        False,
        True,
    )
    assert (body["inbox_count"], body["default_inbox_count"]) == (1, 0)
    assert body["status"]["state"] == "unknown"
    (sent,) = mailer.sent
    assert sent.rcpt_to == ["owner@acme.example"]
    user = await session.scalar(select(User).where(User.username == "acme"))
    assert user is not None
    assert (user.email, user.password_hash, user.role) == (None, None, UserRole.USER)
    inbox = await default_inbox(session, user)
    assert inbox.verified_at is None and inbox.forward_by_default is True
    assert ("kv.sync_subdomain", str(user.id)) in dispatched


@pytest.mark.usefixtures("dispatched")
async def test_duplicate_and_reserved_labels_are_refused(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """A taken label conflicts; a reserved or malformed one is invalid."""
    await _operator(client, session)
    await _create(client)
    duplicate = await client.post(API, json={"label": "acme", "inbox_email": "x@example.org"})
    assert duplicate.status_code == 409
    for label in ("rp", "admin", "-bad"):
        response = await client.post(API, json={"label": label, "inbox_email": "x@example.org"})
        assert response.status_code == 422, label


@pytest.mark.usefixtures("dispatched")
async def test_list_puts_the_operator_first(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """The operator's own subdomain is listed first, then the others by label."""
    await _operator(client, session)
    for label in ("zeta", "acme"):
        await _create(client, label)
    listed = (await client.get(API)).json()
    assert [s["label"] for s in listed] == ["boss", "acme", "zeta"]
    assert listed[0]["is_operator"] is True
    assert listed[0]["default_inbox_count"] == 1


async def test_suspend_stops_forwarding_and_updates_the_edge(
    session: AsyncSession, client: httpx.AsyncClient, dispatched: list[tuple[str, str]]
) -> None:
    """Suspending queues a KV sync, and mail to the subdomain is then discarded."""
    h = await make_harness(session)
    acme = await UserService(session).create_user("acme", "acme@example.com", PASSWORD)
    alias = await AliasService(session, get_settings()).create(acme, local_part="acme-shop")
    await session.commit()
    login = await client.post("/api/v1/auth/login", json={"username": "pia", "password": "x" * 12})
    assert login.status_code == 200
    dispatched.clear()
    response = await client.patch(f"{API}/acme", json={"suspended": True})
    assert response.status_code == 200 and response.json()["suspended"] is True
    assert ("kv.sync_subdomain", str(acme.id)) in dispatched
    h.enqueue("fwd_alternative.eml", rcpt_to=alias.address)
    await h.processor.run_once()
    assert h.mailer.sent == []
    log = await session.scalar(select(MailLog).where(MailLog.user_id == acme.id))
    assert log is not None
    assert (log.outcome, log.reason) == (Outcome.DISCARDED, "user_disabled")


@pytest.mark.usefixtures("dispatched")
async def test_limits_are_validated_and_can_be_cleared(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Only known limit keys with positive values are accepted."""
    await _operator(client, session)
    await _create(client)
    set_ = await client.patch(f"{API}/acme", json={"limits": {"sends_per_day": 5}})
    assert set_.status_code == 200
    assert set_.json()["limits"] == {"sends_per_day": 5} and set_.json()["send_share"] == 5
    assert (await client.patch(f"{API}/acme", json={"limits": {"bogus": 1}})).status_code == 422
    assert (
        await client.patch(f"{API}/acme", json={"limits": {"sends_per_day": 0}})
    ).status_code == 422
    cleared = await client.patch(f"{API}/acme", json={"clear_limits": True})
    assert cleared.json()["limits"] is None
    assert cleared.json()["send_share"] == get_settings().subdomain_sends_per_day


async def test_retire_forgets_aliases_and_disables_inboxes(
    client: httpx.AsyncClient, session: AsyncSession, dispatched: list[tuple[str, str]]
) -> None:
    """Retiring keeps every row but forgets the aliases and turns the inboxes off."""
    await _operator(client, session)
    await _create(client)
    acme = await session.scalar(select(User).where(User.username == "acme"))
    assert acme is not None
    alias = await AliasService(session, get_settings()).create(acme, local_part="shop")
    await session.commit()
    response = await client.post(f"{API}/acme/retire")
    assert response.status_code == 200
    assert (response.json()["retired"], response.json()["status"]["state"]) == (True, "retired")
    await session.refresh(alias)
    assert alias.state == AliasState.FORGOTTEN
    inboxes = (await session.scalars(select(Recipient).where(Recipient.user_id == acme.id))).all()
    assert inboxes and all(r.disabled_at is not None for r in inboxes)
    assert ("kv.sync_alias", str(alias.id)) in dispatched
    assert (await client.patch(f"{API}/acme", json={"suspended": False})).status_code == 409


@pytest.mark.usefixtures("dispatched")
async def test_operator_subdomain_cannot_be_suspended_or_retired(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """The operator's own row is protected."""
    await _operator(client, session)
    for response in (
        await client.patch(f"{API}/boss", json={"suspended": True}),
        await client.post(f"{API}/boss/retire"),
    ):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "operator_subdomain"


@pytest.mark.usefixtures("dispatched")
async def test_api_tokens_cannot_reach_operator_routes(
    app: FastAPI, client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """A subdomain token gets 403 on every /operator route."""
    await _operator(client, session)
    await _create(client)
    created = await client.post(
        sub("acme", "/tokens"), json={"name": "script", "scopes": ["aliases:read"]}
    )
    headers = {"Authorization": f"Bearer {created.json()['token']}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as bare:
        for method, url in (
            ("GET", API),
            ("GET", f"{API}/acme"),
            ("GET", "/api/v1/operator/health"),
            ("GET", "/api/v1/operator/dlq"),
        ):
            response = await bare.request(method, url, headers=headers)
            assert response.status_code == 403, url


def _cleanup(*labels: str) -> list[tuple[str, bool, bool]]:
    """Read each label's first inbox flags, then delete the rows (the CLI commits for real).

    Args:
        labels: Usernames to remove.
    Returns:
        (label, inbox verified, inbox is default) for each label that existed.
    """
    import asyncio

    from sqlalchemy import delete

    from mailalias.db import get_engine, get_session_factory

    async def _run() -> list[tuple[str, bool, bool]]:
        found = []
        try:
            async with get_session_factory()() as db:
                for label in labels:
                    user = await db.scalar(select(User).where(User.username == label))
                    if user is None:
                        continue
                    inbox = await db.scalar(select(Recipient).where(Recipient.user_id == user.id))
                    if inbox is not None:
                        found.append(
                            (label, inbox.verified_at is not None, inbox.forward_by_default)
                        )
                    await db.execute(delete(Recipient).where(Recipient.user_id == user.id))
                    await db.execute(delete(User).where(User.id == user.id))
                await db.commit()
        finally:
            await get_engine().dispose()
        return found

    return asyncio.run(_run())


def test_cli_create_subdomain(migrated_db: str, dispatched: list[tuple[str, str]]) -> None:
    """`mailalias create-subdomain` creates the subdomain with an unverified default inbox.

    Args:
        migrated_db: Ensures the test database exists.
        dispatched: Captures the KV sync instead of calling Celery.
    Returns:
        None.
    """
    import asyncio
    import secrets

    from typer.testing import CliRunner

    from mailalias.cli import app as cli_app
    from mailalias.db import get_engine, get_session_factory

    operator, label = f"op-{secrets.token_hex(3)}", f"cli-{secrets.token_hex(3)}"

    async def _operator() -> None:
        try:
            async with get_session_factory()() as db:
                await UserService(db).create_user(
                    operator, f"{operator}@example.com", PASSWORD, UserRole.ADMIN
                )
                await db.commit()
        finally:
            await get_engine().dispose()

    asyncio.run(_operator())
    try:
        result = CliRunner().invoke(
            cli_app,
            ["create-subdomain", "--label", label, "--inbox", "owner@cli.example"],
        )
    finally:
        found = _cleanup(label, operator)
    assert result.exit_code == 0, result.output
    assert f"subdomain '{label}' created" in result.output
    assert (label, False, True) in found
