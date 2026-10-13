"""Health endpoint reports database and Redis status."""

# 3rd party imports
import httpx


async def test_healthz_ok(client: httpx.AsyncClient) -> None:
    """With Postgres and Redis up, /healthz returns 200 and both ok.

    Args:
        client: In-process HTTP client.
    Returns:
        None.
    """
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"db": "ok", "redis": "ok"}
