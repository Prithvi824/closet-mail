"""Rspamd spam scoring over its HTTP scan API (/checkv2)."""

# 1st party imports
import asyncio
import contextlib
import logging
import socket
from dataclasses import dataclass
from typing import Protocol

# 3rd party imports
import httpx

# local imports
from mailalias.config import Settings

logger = logging.getLogger(__name__)

PTR_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class SpamVerdict:
    """Rspamd's total score and the names of the symbols that fired."""

    score: float
    symbols: tuple[str, ...]


class SpamCheckUnavailable(Exception):
    """Rspamd could not be reached or answered with an error."""


class SpamChecker(Protocol):
    """Anything that can score a raw message."""

    async def check(
        self, raw: bytes, mail_from: str, rcpt: str, ip: str | None, helo: str | None
    ) -> SpamVerdict:
        """Score one message; raises SpamCheckUnavailable."""
        ...


async def reverse_dns(ip: str) -> str | None:
    """PTR name of an IP (Rspamd needs it from the MTA; we are the MTA here).

    Args:
        ip: Client IP.
    Returns:
        Hostname, or None if there is no PTR record or the lookup is slow.
    """
    loop = asyncio.get_running_loop()
    with contextlib.suppress(OSError, TimeoutError, UnicodeError):
        host, _ = await asyncio.wait_for(
            loop.getnameinfo((ip, 0), socket.NI_NAMEREQD), PTR_TIMEOUT_SECONDS
        )
        return host
    return None


class RspamdClient:
    """Scores messages with POST /checkv2, passing the real SMTP client details."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        """Build the client.

        Args:
            settings: rspamd_url and the timeout.
            client: Optional pre-built httpx client (tests).
        Returns:
            None.
        """
        self.url = settings.rspamd_url.rstrip("/") + "/checkv2"
        self._client = client or httpx.AsyncClient(timeout=settings.spam_check_timeout_seconds)

    async def check(
        self, raw: bytes, mail_from: str, rcpt: str, ip: str | None, helo: str | None
    ) -> SpamVerdict:
        """Score one message.

        Args:
            raw: Raw message bytes.
            mail_from, rcpt: Envelope addresses.
            ip, helo: SMTP client details from Cloudflare (enable SPF/rDNS checks), if known.
        Returns:
            The verdict. Raises SpamCheckUnavailable.
        """
        headers = {"Rcpt": rcpt, "From": mail_from or "<>"}
        if ip:
            headers["IP"] = ip
            hostname = await reverse_dns(ip)
            if hostname:
                headers["Hostname"] = hostname
        if helo:
            headers["Helo"] = helo
        try:
            response = await self._client.post(self.url, content=raw, headers=headers)
            response.raise_for_status()
            body = response.json()
            return SpamVerdict(float(body["score"]), tuple(sorted(body.get("symbols") or {})))
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise SpamCheckUnavailable(type(exc).__name__) from exc

    async def aclose(self) -> None:
        """Close the HTTP client.

        Returns:
            None.
        """
        await self._client.aclose()
