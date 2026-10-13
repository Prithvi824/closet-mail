"""FastAPI application factory (`uvicorn mailalias.api.app:create_app --factory`)."""

# 1st party imports
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

# 3rd party imports
from fastapi import APIRouter, FastAPI

# local imports
from mailalias import __version__
from mailalias.api.errors import install_error_handlers
from mailalias.api.ratelimit import API_PREFIX, SecurityMiddleware
from mailalias.api.routes import (
    actions,
    admin,
    aliases,
    auth,
    blocklist,
    contacts,
    failed,
    health,
    hooks,
    labels,
    me,
    quarantine,
    recipients,
    tokens,
)
from mailalias.config import get_settings
from mailalias.db import get_engine, get_redis
from mailalias.logging_setup import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Set up file logging on startup; release shared connections on shutdown.

    Args:
        app: The application.
    Returns:
        An async context manager.
    """
    configure_logging("api")
    yield
    await get_redis().aclose()
    await get_engine().dispose()


def build_api_router() -> APIRouter:
    """Collect all `/api/v1` routers.

    Returns:
        The versioned API router.
    """
    router = APIRouter(prefix=API_PREFIX)
    for module in (
        auth,
        me,
        recipients,
        aliases,
        contacts,
        labels,
        blocklist,
        quarantine,
        failed,
        tokens,
        admin,
    ):
        router.include_router(module.router)
    return router


def create_app() -> FastAPI:
    """Create the configured FastAPI application.

    Returns:
        The app with routes, middleware and error handlers installed.
    """
    # The interactive docs load scripts from a CDN, which the production CSP forbids.
    docs = get_settings().app_env != "prod"
    app = FastAPI(
        title="mail-alias",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
    )
    install_error_handlers(app)
    app.add_middleware(SecurityMiddleware)
    app.include_router(health.router)
    app.include_router(actions.router)
    app.include_router(hooks.router)
    app.include_router(build_api_router())
    return app
