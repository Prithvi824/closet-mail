"""Read-only Cloudflare DNS lookups for the zone, used to check each subdomain's mail routing."""

# 1st party imports
from dataclasses import dataclass
from typing import Literal

# local imports
from mailalias.integrations.cloudflare_api import CloudflareApi

PER_PAGE = 50


@dataclass(frozen=True)
class DnsRecord:
    """One DNS record (MX contents are lowercased without the trailing dot)."""

    type: str
    name: str
    content: str
    priority: int | None


class CloudflareDns:
    """Lists DNS records of one zone. It never writes."""

    def __init__(self, api: CloudflareApi, zone_id: str) -> None:
        """Build the client.

        Args:
            api: Cloudflare API client.
            zone_id: Zone id (CF_ZONE_ID).
        Returns:
            None.
        """
        self._api = api
        self._url = api.zone_path(zone_id, "/dns_records")

    async def records(self, name: str, record_type: Literal["MX", "TXT"]) -> list[DnsRecord]:
        """Records of one type at one name, straight from Cloudflare (no resolver caching).

        Args:
            name: Fully qualified name, e.g. "acme.closetcompute.online".
            record_type: "MX" or "TXT".
        Returns:
            The records. Raises RetryableError or CloudflareApiError.
        """
        payload = await self._api.json(
            "dns.list",
            "GET",
            self._url,
            params={"name": name, "type": record_type, "per_page": PER_PAGE},
        )
        records = []
        for item in payload.get("result") or []:
            content = str(item.get("content", ""))
            if record_type == "MX":
                content = content.lower().rstrip(".")
            priority = item.get("priority")
            records.append(
                DnsRecord(
                    type=str(item.get("type", record_type)),
                    name=str(item.get("name", name)),
                    content=content,
                    priority=int(priority) if priority is not None else None,
                )
            )
        return records
