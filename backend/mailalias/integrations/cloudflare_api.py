"""Thin async client for the Cloudflare REST API with retry on 429/5xx."""

# 1st party imports
import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

# 3rd party imports
import httpx

# local imports
from mailalias.config import Settings
from mailalias.mail.types import RetryableError

logger = logging.getLogger(__name__)

CF_API_BASE = "https://api.cloudflare.com/client/v4"
MAX_ATTEMPTS = 3
BASE_BACKOFF_SECONDS = 0.5


class CloudflareApiError(Exception):
    """Permanent API failure (4xx other than 429, or success=false)."""

    def __init__(self, label: str, status: int, codes: list[int]) -> None:
        """Create the error without echoing request data.

        Args:
            label: Short operation name, e.g. "queue.pull".
            status: HTTP status code.
            codes: Cloudflare error codes from the response.
        Returns:
            None.
        """
        super().__init__(f"cloudflare {label} failed: http {status}, codes {codes}")
        self.status = status
        self.codes = codes


class CloudflareApi:
    """Account-scoped Cloudflare API client. One instance per process is enough."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Build the client.

        Args:
            settings: Provides the token and account id.
            client: Optional pre-built httpx client (tests).
            sleep: Backoff sleeper, injectable for tests.
        Returns:
            None.
        """
        self.account_id = settings.cf_account_id
        self._sleep = sleep
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        self._headers = {"Authorization": f"Bearer {settings.cf_api_token.get_secret_value()}"}

    def account_path(self, suffix: str) -> str:
        """Build an account-scoped URL.

        Args:
            suffix: Path after /accounts/{id}, starting with "/".
        Returns:
            The absolute URL.
        """
        return f"{CF_API_BASE}/accounts/{self.account_id}{suffix}"

    async def request(self, label: str, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send a request, retrying 429/5xx/transport errors with exponential backoff.

        Args:
            label: Operation name used in logs and errors (never the URL, which may hold keys).
            method: HTTP method.
            url: Absolute URL.
            kwargs: Passed to httpx (json, params, content, headers).
        Returns:
            The successful response. Raises RetryableError or CloudflareApiError.
        """
        headers = {**self._headers, **kwargs.pop("headers", {})}
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await self._client.request(method, url, headers=headers, **kwargs)
            except httpx.TransportError as exc:
                failure = type(exc).__name__
            else:
                if response.status_code == 429 or response.status_code >= 500:
                    failure = f"http {response.status_code}"
                elif response.status_code >= 400:
                    raise CloudflareApiError(label, response.status_code, _error_codes(response))
                else:
                    return response
            if attempt < MAX_ATTEMPTS:
                logger.warning("cloudflare retry", extra={"op": label, "attempt": attempt})
                await self._sleep(BASE_BACKOFF_SECONDS * 2 ** (attempt - 1))
        raise RetryableError(f"cloudflare {label} unavailable ({failure})")

    async def json(self, label: str, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        """Send a request and return the decoded envelope, checking `success`.

        Args:
            label: Operation name.
            method: HTTP method.
            url: Absolute URL.
            kwargs: Passed to `request`.
        Returns:
            The full JSON envelope (with "result").
        """
        response = await self.request(label, method, url, **kwargs)
        payload: dict[str, Any] = response.json()
        if not payload.get("success", False):
            raise CloudflareApiError(label, response.status_code, _error_codes(response))
        return payload

    async def aclose(self) -> None:
        """Close the underlying HTTP client.

        Returns:
            None.
        """
        await self._client.aclose()


def _error_codes(response: httpx.Response) -> list[int]:
    """Extract Cloudflare error codes from a response, tolerating non-JSON bodies.

    Args:
        response: The HTTP response.
    Returns:
        A list of integer error codes (possibly empty).
    """
    try:
        errors = response.json().get("errors") or []
    except ValueError:
        return []
    return [int(e.get("code", 0)) for e in errors if isinstance(e, dict)]
