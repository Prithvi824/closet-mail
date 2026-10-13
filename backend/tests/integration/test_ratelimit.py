"""Fixed-window rate limits and X-RateLimit-* headers."""

# 3rd party imports
import httpx
from fastapi import APIRouter, FastAPI

# local imports
from mailalias.api.ratelimit import AUTH_LIMIT


def _add_auth_probe(app: FastAPI) -> None:
    """Mount a trivial endpoint under /api/v1/auth.

    Args:
        app: The application.
    Returns:
        None.
    """
    router = APIRouter(prefix="/api/v1/auth")

    @router.get("/probe")
    async def probe() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router)


async def test_auth_paths_limited_per_ip(app: FastAPI, client: httpx.AsyncClient) -> None:
    """The 6th auth request in a window from one IP gets 429 with limit headers.

    Args:
        app: The application.
        client: HTTP client.
    Returns:
        None.
    """
    _add_auth_probe(app)
    ip = {"CF-Connecting-IP": "203.0.113.7"}
    for remaining in range(AUTH_LIMIT - 1, -1, -1):
        ok = await client.get("/api/v1/auth/probe", headers=ip)
        assert ok.status_code == 200
        assert ok.headers["X-RateLimit-Remaining"] == str(remaining)

    blocked = await client.get("/api/v1/auth/probe", headers=ip)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert blocked.headers["X-RateLimit-Limit"] == str(AUTH_LIMIT)
    assert blocked.headers["X-RateLimit-Remaining"] == "0"
    assert int(blocked.headers["Retry-After"]) >= 1

    other_ip = await client.get("/api/v1/auth/probe", headers={"CF-Connecting-IP": "203.0.113.8"})
    assert other_ip.status_code == 200


async def test_non_api_paths_are_not_limited(client: httpx.AsyncClient) -> None:
    """/healthz carries no rate-limit headers.

    Args:
        client: HTTP client.
    Returns:
        None.
    """
    response = await client.get("/healthz")
    assert "X-RateLimit-Limit" not in response.headers
