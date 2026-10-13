"""Liveness/readiness endpoint used by Docker, deploy scripts and monitors."""

# 3rd party imports
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

# local imports
from mailalias.api.deps import DbSession
from mailalias.db import get_redis

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz(db: DbSession) -> JSONResponse:
    """Check Postgres and Redis connectivity.

    Args:
        db: Database session.
    Returns:
        200 {"db": "ok", "redis": "ok"} or 503 naming the failing part.
    """
    status = {"db": "ok", "redis": "ok"}
    try:
        await db.execute(text("select 1"))
    except Exception:  # any driver/network error means "not ready"
        status["db"] = "error"
    try:
        await get_redis().ping()
    except Exception:
        status["redis"] = "error"
    healthy = all(value == "ok" for value in status.values())
    return JSONResponse(status, status_code=200 if healthy else 503)
