"""Subdomain status: is each subdomain set up to receive mail? Reads DNS and KV, never writes."""

# 1st party imports
import logging
from datetime import UTC, datetime
from typing import Literal, Protocol

# 3rd party imports
import httpx
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.config import Settings
from mailalias.integrations.cloudflare_api import CloudflareApiError
from mailalias.integrations.cloudflare_dns import DnsRecord
from mailalias.mail.types import RetryableError
from mailalias.models import Recipient, SubdomainState, SubdomainStatus, User
from mailalias.services import kv_sync

logger = logging.getLogger(__name__)

EXPECTED_MX = {"route1.mx.cloudflare.net", "route2.mx.cloudflare.net", "route3.mx.cloudflare.net"}
SPF_INCLUDE = "include:_spf.mx.cloudflare.net"
LOOKUP_FAILED = "Cloudflare lookup failed"
# Errors that mean "Cloudflare could not answer", which must never break a check.
CLOUDFLARE_ERRORS = (RetryableError, CloudflareApiError, httpx.HTTPError)


class DnsReader(Protocol):
    """What the checker needs from CloudflareDns."""

    async def records(self, name: str, record_type: Literal["MX", "TXT"]) -> list[DnsRecord]:
        """Records of one type at one name.

        Args:
            name: FQDN.
            record_type: "MX" or "TXT".
        Returns:
            The records.
        """
        ...


class KvReader(Protocol):
    """What the checker needs from CloudflareKv."""

    async def get(self, key: str) -> str | None:
        """Read one key.

        Args:
            key: KV key.
        Returns:
            The value or None.
        """
        ...


class SubdomainStatusChecker:
    """Checks subdomains against Cloudflare DNS and KV and stores one status row each."""

    def __init__(
        self, db: AsyncSession, dns: DnsReader | None, kv: KvReader, settings: Settings
    ) -> None:
        """Build the checker.

        Args:
            db: Session (the caller commits).
            dns: DNS reader; None when no zone is configured (lookups count as failed).
            kv: KV reader for the s:<label> catch-all flag.
            settings: Alias domain.
        Returns:
            None.
        """
        self.db = db
        self.dns = dns
        self.kv = kv
        self.settings = settings

    async def _has_default_inbox(self, user: User) -> bool:
        """Whether a verified, enabled default inbox exists.

        Args:
            user: Subdomain.
        Returns:
            True if mail with no ticked inbox has somewhere to go.
        """
        query = select(
            exists().where(
                Recipient.user_id == user.id,
                Recipient.forward_by_default.is_(True),
                Recipient.verified_at.is_not(None),
                Recipient.disabled_at.is_(None),
            )
        )
        return bool(await self.db.scalar(query))

    async def _dns(self, fqdn: str) -> tuple[bool | None, bool | None]:
        """MX and SPF checks for one name.

        Args:
            fqdn: e.g. "acme.closetcompute.online".
        Returns:
            (mx_ok, spf_ok); both None when Cloudflare could not be read.
        """
        if self.dns is None:
            return None, None
        try:
            mx = {record.content for record in await self.dns.records(fqdn, "MX")}
            txt = [record.content for record in await self.dns.records(fqdn, "TXT")]
        except CLOUDFLARE_ERRORS as exc:
            logger.warning("subdomain dns lookup failed", extra={"error": type(exc).__name__})
            return None, None
        return mx >= EXPECTED_MX, any(SPF_INCLUDE in value for value in txt)

    async def _kv_ok(self, user: User) -> bool | None:
        """Whether the edge's catch-all flag matches what the subdomain wants.

        Args:
            user: Subdomain.
        Returns:
            True/False, or None when KV could not be read.
        """
        try:
            present = await self.kv.get(f"{kv_sync.SUBDOMAIN_PREFIX}{user.username}") is not None
        except CLOUDFLARE_ERRORS as exc:
            logger.warning("subdomain kv lookup failed", extra={"error": type(exc).__name__})
            return None
        return present == kv_sync.subdomain_enabled(user)

    async def check(self, user: User) -> SubdomainStatus:
        """Check one subdomain and upsert its status row; Cloudflare errors never raise.

        Args:
            user: Subdomain (users row).
        Returns:
            The stored status.
        """
        fqdn = f"{user.username}.{self.settings.alias_domain}"
        mx_ok, spf_ok = await self._dns(fqdn)
        kv_ok = await self._kv_ok(user)
        detail: str | None = None
        if user.retired_at is not None:
            state = SubdomainState.RETIRED
        elif user.disabled_at is not None:
            state = SubdomainState.SUSPENDED
        elif not await self._has_default_inbox(user):
            state, detail = SubdomainState.NO_INBOX, "No verified default inbox"
        elif mx_ok is None:
            state, detail = SubdomainState.UNKNOWN, LOOKUP_FAILED
        elif not mx_ok:
            state = SubdomainState.DNS_MISSING
            detail = f"Cloudflare MX records for {fqdn} are missing; add it under Email Routing"
        else:
            state = SubdomainState.READY
        if state == SubdomainState.NO_INBOX and mx_ok is None:
            detail = f"{detail}; {LOOKUP_FAILED}"
        status = await self.db.get(SubdomainStatus, user.id)
        if status is None:
            status = SubdomainStatus(user_id=user.id)
            self.db.add(status)
        status.state = state
        status.mx_ok, status.spf_ok, status.kv_ok = mx_ok, spf_ok, kv_ok
        status.detail = detail
        status.checked_at = datetime.now(UTC)
        await self.db.flush()
        return status

    async def check_all(self) -> int:
        """Check every subdomain that is not retired.

        Returns:
            Number of subdomains checked.
        """
        users = list(await self.db.scalars(select(User).where(User.retired_at.is_(None))))
        for user in users:
            await self.check(user)
        return len(users)
