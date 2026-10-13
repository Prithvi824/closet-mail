"""Domain errors raised by services and their mapping to JSON HTTP errors."""

# 3rd party imports
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class DomainError(Exception):
    """Base for expected business-rule failures. Message must be safe to show users."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, code: str | None = None) -> None:
        """Create the error.

        Args:
            message: Human-readable, user-safe message.
            code: Optional machine code overriding the class default.
        Returns:
            None.
        """
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFound(DomainError):
    """Resource missing or not owned by the caller."""

    status_code = 404
    code = "not_found"


class Conflict(DomainError):
    """Uniqueness or state conflict."""

    status_code = 409
    code = "conflict"


class Forbidden(DomainError):
    """Authenticated but not allowed."""

    status_code = 403
    code = "forbidden"


class Unauthorized(DomainError):
    """Not authenticated, or the session is no longer valid."""

    status_code = 401
    code = "unauthorized"


class ValidationFailed(DomainError):
    """Input is well-formed but violates a rule."""

    status_code = 422
    code = "validation_failed"


class QuotaExceeded(DomainError):
    """A rate or usage limit was hit."""

    status_code = 429
    code = "quota_exceeded"


def error_body(code: str, message: str) -> dict[str, dict[str, str]]:
    """Build the standard error payload.

    Args:
        code: Machine-readable code.
        message: Human-readable message.
    Returns:
        {"error": {"code": ..., "message": ...}}.
    """
    return {"error": {"code": code, "message": message}}


async def _domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render a DomainError.

    Args:
        request: Incoming request (unused).
        exc: The DomainError.
    Returns:
        JSON error response with the error's status.
    """
    assert isinstance(exc, DomainError)
    return JSONResponse(error_body(exc.code, exc.message), status_code=exc.status_code)


async def _http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render Starlette/FastAPI HTTPExceptions in the standard shape.

    Args:
        request: Incoming request (unused).
        exc: The HTTPException.
    Returns:
        JSON error response preserving status and headers.
    """
    assert isinstance(exc, StarletteHTTPException)
    code = {
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        429: "rate_limited",
    }.get(exc.status_code, "http_error")
    return JSONResponse(
        error_body(code, str(exc.detail)), status_code=exc.status_code, headers=exc.headers
    )


async def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render request validation errors (bad JSON / fields) as 422.

    Args:
        request: Incoming request (unused).
        exc: The RequestValidationError.
    Returns:
        JSON error response listing the failing fields.
    """
    assert isinstance(exc, RequestValidationError)
    fields = ", ".join(".".join(str(p) for p in err["loc"][1:]) for err in exc.errors())
    return JSONResponse(error_body("invalid_request", f"Invalid fields: {fields}"), status_code=422)


def install_error_handlers(app: FastAPI) -> None:
    """Register all error handlers on the app.

    Args:
        app: The FastAPI application.
    Returns:
        None.
    """
    app.add_exception_handler(DomainError, _domain_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
