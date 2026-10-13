"""Fixed-window rate limiting (Redis) and CSRF header enforcement as ASGI middleware."""

# 1st party imports
import time
from collections.abc import Awaitable, Callable

# 3rd party imports
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# local imports
from mailalias.api.errors import error_body
from mailalias.db import get_redis
from mailalias.security.sessions import SESSION_COOKIE

API_PREFIX = "/api/v1"
AUTH_PREFIX = f"{API_PREFIX}/auth/"
WINDOW_SECONDS = 60
DEFAULT_LIMIT = 60
AUTH_LIMIT = 5
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "mailalias"
# Plain HTML forms opened from email; the URL token itself is the credential.
CSRF_EXEMPT_PREFIXES = (f"{API_PREFIX}/recipients/verify/",)

Handler = Callable[[Request], Awaitable[Response]]


def client_ip(request: Request) -> str:
    """Best-effort client IP: Cloudflare's header first, then the socket peer.

    Args:
        request: Incoming request.
    Returns:
        The IP string, or "unknown".
    """
    forwarded = request.headers.get("CF-Connecting-IP")
    if forwarded:
        return forwarded.strip()
    return request.client.host if request.client else "unknown"


def bearer_prefix(request: Request) -> str | None:
    """Return the public prefix of a bearer API token, if one is presented.

    Args:
        request: Incoming request.
    Returns:
        The token prefix (never the secret), or None.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    parts = auth[7:].strip().split("_")
    return parts[1] if len(parts) >= 3 and parts[0] == "ma" else "invalid"


def rate_limit_bucket(request: Request) -> tuple[str, int] | None:
    """Choose the limiter key and limit for a request.

    Args:
        request: Incoming request.
    Returns:
        (bucket key, limit) or None when the path is not rate limited.
    """
    path = request.url.path
    if not path.startswith(API_PREFIX):
        return None
    if path.startswith(AUTH_PREFIX):
        return f"ip:{client_ip(request)}:auth", AUTH_LIMIT
    token = bearer_prefix(request)
    if token:
        return f"tok:{token}", DEFAULT_LIMIT
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        return f"sess:{sid[:16]}", DEFAULT_LIMIT
    return f"ip:{client_ip(request)}", DEFAULT_LIMIT


class SecurityMiddleware(BaseHTTPMiddleware):
    """Enforces the CSRF header on cookie-authenticated writes and per-client rate limits."""

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        """Check CSRF, apply the rate limit, and add X-RateLimit-* headers.

        Args:
            request: Incoming request.
            call_next: Downstream handler.
        Returns:
            The downstream response, or a 403/429 error.
        """
        is_api = request.url.path.startswith(API_PREFIX)
        if (
            is_api
            and request.method in MUTATING_METHODS
            and bearer_prefix(request) is None
            and not request.url.path.startswith(CSRF_EXEMPT_PREFIXES)
            and request.headers.get(CSRF_HEADER) != CSRF_VALUE
        ):
            return JSONResponse(error_body("csrf", "Missing CSRF header"), status_code=403)

        bucket = rate_limit_bucket(request)
        if bucket is None:
            return await call_next(request)

        key, limit = bucket
        window = int(time.time() // WINDOW_SECONDS)
        reset = (window + 1) * WINDOW_SECONDS
        redis = get_redis()
        redis_key = f"rl:{key}:{window}"
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(redis_key)
            pipe.expire(redis_key, WINDOW_SECONDS + 5)
            count, _ = await pipe.execute()
        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(max(limit - int(count), 0)),
            "X-RateLimit-Reset": str(reset),
        }
        if int(count) > limit:
            headers["Retry-After"] = str(max(reset - int(time.time()), 1))
            return JSONResponse(
                error_body("rate_limited", "Too many requests"), status_code=429, headers=headers
            )
        response = await call_next(request)
        response.headers.update(headers)
        return response
