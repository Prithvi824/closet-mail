"""Subdomain scoping: every per-subdomain route goes through current_subdomain."""

# 1st party imports
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

# 3rd party imports
import httpx
import pytest
from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.deps import current_subdomain, current_user
from mailalias.config import get_settings
from mailalias.models import User, UserRole
from mailalias.services.aliases import AliasService
from mailalias.services.users import UserService
from tests.integration.harness import sub

pytestmark = pytest.mark.usefixtures("dispatched", "relaxed_rate_limits")
PASSWORD = "correct horse battery"
SCOPE = "/api/v1/subdomains/"


def _calls(dependant: Dependant) -> Iterator[Callable[..., Any]]:
    """Every dependency callable in a route's dependency tree.

    Args:
        dependant: The route's dependant.
    Returns:
        An iterator of callables.
    """
    for dependency in dependant.dependencies:
        if dependency.call is not None:
            yield dependency.call
        yield from _calls(dependency)


def _api_routes(app: FastAPI) -> list[RouteContext]:
    """All /api/v1 routes with their full paths and combined dependencies.

    Args:
        app: Application.
    Returns:
        The route contexts (included routers are resolved lazily by FastAPI).
    """
    routes = [
        r
        for r in iter_route_contexts(app.routes)
        if isinstance(r.original_route, APIRoute) and (r.path or "").startswith("/api/v1")
    ]
    assert routes, "no API routes found"
    return routes


def test_every_subdomain_route_resolves_the_subdomain(app: FastAPI) -> None:
    """No route under /subdomains/{label} can skip the scope check."""
    scoped = [r for r in _api_routes(app) if r.path.startswith(SCOPE)]
    assert len(scoped) > 20
    for route in scoped:
        assert current_subdomain in set(_calls(route.dependant)), route.path


def test_only_operator_identity_routes_use_the_signed_in_user(app: FastAPI) -> None:
    """Outside the scope, only /me routes read the signed-in user as a data owner."""
    for route in _api_routes(app):
        if route.path.startswith(SCOPE) or route.path.startswith("/api/v1/me"):
            continue
        assert current_user not in set(_calls(route.dependant)), route.path


async def _setup(client: httpx.AsyncClient, session: AsyncSession) -> tuple[User, User]:
    """Operator "boss" signed in, plus subdomains "acme" (with an alias) and "beta".

    Args:
        client: HTTP client.
        session: Test session.
    Returns:
        (acme, beta).
    """
    users = UserService(session)
    await users.create_user("boss", "boss@example.com", PASSWORD, UserRole.ADMIN)
    acme = await users.create_user("acme", "acme@example.com", PASSWORD)
    beta = await users.create_user("beta", "beta@example.com", PASSWORD)
    await AliasService(session, get_settings()).create(acme, local_part="shop")
    await session.commit()
    login = await client.post("/api/v1/auth/login", json={"username": "boss", "password": PASSWORD})
    assert login.status_code == 200
    return acme, beta


async def test_operator_reads_any_subdomain(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """The operator session sees each subdomain's own data under its label."""
    await _setup(client, session)
    acme = (await client.get(sub("acme", "/aliases"))).json()
    beta = (await client.get(sub("beta", "/aliases"))).json()
    assert [a["address"] for a in acme["items"]] == ["shop@closetcompute.online"]
    assert beta["items"] == []
    assert (await client.get(sub("nope", "/aliases"))).status_code == 404


async def test_token_cannot_leave_its_subdomain(
    app: FastAPI, client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """A token made for acme reads acme and gets 404 on beta."""
    await _setup(client, session)
    created = await client.post(
        sub("acme", "/tokens"), json={"name": "script", "scopes": ["aliases:read"]}
    )
    assert created.status_code == 201
    headers = {"Authorization": f"Bearer {created.json()['token']}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as bare:
        assert (await bare.get(sub("acme", "/aliases"), headers=headers)).status_code == 200
        assert (await bare.get(sub("beta", "/aliases"), headers=headers)).status_code == 404


async def test_retired_subdomain_is_read_only(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """A retired subdomain can be read but not changed."""
    acme, _ = await _setup(client, session)
    acme.retired_at = datetime.now(UTC)
    await session.commit()
    assert (await client.get(sub("acme", "/aliases"))).status_code == 200
    created = await client.post(sub("acme", "/aliases"), json={"local_part": "late"})
    assert created.status_code == 409 and created.json()["error"]["code"] == "retired"
