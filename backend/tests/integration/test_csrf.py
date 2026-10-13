"""CSRF header enforcement and the standard error shape."""

# 3rd party imports
import httpx
from fastapi import APIRouter, FastAPI


def _add_probe_route(app: FastAPI) -> None:
    """Mount a trivial mutating endpoint under /api/v1 for the tests.

    Args:
        app: The application.
    Returns:
        None.
    """
    router = APIRouter(prefix="/api/v1")

    @router.post("/probe")
    async def probe() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router)


async def test_post_without_csrf_header_is_rejected(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """A cookie-style POST without X-Requested-With gets 403 in the error shape.

    Args:
        app: The application.
        client: HTTP client (CSRF header removed for this call).
    Returns:
        None.
    """
    _add_probe_route(app)
    response = await client.post("/api/v1/probe", headers={"X-Requested-With": ""})
    assert response.status_code == 403
    assert response.json() == {"error": {"code": "csrf", "message": "Missing CSRF header"}}


async def test_post_with_csrf_header_passes(app: FastAPI, client: httpx.AsyncClient) -> None:
    """The same POST with the header succeeds.

    Args:
        app: The application.
        client: HTTP client sending the CSRF header.
    Returns:
        None.
    """
    _add_probe_route(app)
    response = await client.post("/api/v1/probe")
    assert response.status_code == 200


async def test_bearer_requests_skip_csrf(app: FastAPI, client: httpx.AsyncClient) -> None:
    """Token-authenticated requests are not subject to the CSRF header.

    Args:
        app: The application.
        client: HTTP client.
    Returns:
        None.
    """
    _add_probe_route(app)
    response = await client.post(
        "/api/v1/probe",
        headers={"X-Requested-With": "", "Authorization": "Bearer ma_abcdefgh_secret"},
    )
    assert response.status_code == 200


async def test_unknown_route_uses_error_shape(client: httpx.AsyncClient) -> None:
    """404s use {"error": {...}}.

    Args:
        client: HTTP client.
    Returns:
        None.
    """
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
