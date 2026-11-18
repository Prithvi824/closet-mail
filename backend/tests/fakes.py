"""Reusable in-memory fakes for external services."""

# 1st party imports
from collections.abc import AsyncIterator
from typing import Literal

# local imports
from mailalias.integrations.cloudflare_dns import DnsRecord


class FakeKv:
    """Dict-backed stand-in for CloudflareKv; writes also set the {"v": value} metadata."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        """Create the store (initial keys have no metadata, like keys written before it existed).

        Args:
            initial: Starting keys.
        Returns:
            None.
        """
        self.data: dict[str, str] = dict(initial or {})
        self.metadata: dict[str, str] = {}
        self.writes = 0

    async def put(self, key: str, value: str) -> None:
        """Set a key.

        Args:
            key: Key.
            value: Value.
        Returns:
            None.
        """
        self.data[key] = value
        self.metadata[key] = value
        self.writes += 1

    async def delete(self, key: str) -> None:
        """Remove a key if present.

        Args:
            key: Key.
        Returns:
            None.
        """
        self.data.pop(key, None)
        self.metadata.pop(key, None)

    async def bulk_put(self, items: dict[str, str]) -> None:
        """Set many keys.

        Args:
            items: Key/value pairs.
        Returns:
            None.
        """
        self.data.update(items)
        self.metadata.update(items)
        self.writes += len(items)

    async def bulk_delete(self, keys: list[str]) -> None:
        """Remove many keys.

        Args:
            keys: Keys.
        Returns:
            None.
        """
        for key in keys:
            self.data.pop(key, None)
            self.metadata.pop(key, None)

    async def list_keys(self, prefix: str) -> AsyncIterator[str]:
        """Yield keys with a prefix.

        Args:
            prefix: Key prefix.
        Returns:
            An async iterator of keys.
        """
        for key in sorted(self.data):
            if key.startswith(prefix):
                yield key

    async def list_entries(self, prefix: str) -> AsyncIterator[tuple[str, str | None]]:
        """Yield (key, metadata value) pairs with a prefix.

        Args:
            prefix: Key prefix.
        Returns:
            An async iterator of pairs.
        """
        for key in sorted(self.data):
            if key.startswith(prefix):
                yield key, self.metadata.get(key)

    async def get(self, key: str) -> str | None:
        """Read a key.

        Args:
            key: Key.
        Returns:
            The value or None.
        """
        return self.data.get(key)


class FakeDns:
    """CloudflareDns stand-in: records by (name, type), or an error to raise."""

    def __init__(self, records: dict[tuple[str, str], list[str]] | None = None) -> None:
        """Create the fake.

        Args:
            records: (fqdn, type) -> record contents.
        Returns:
            None.
        """
        self.records_by_key = dict(records or {})
        self.error: Exception | None = None

    async def records(self, name: str, record_type: Literal["MX", "TXT"]) -> list[DnsRecord]:
        """Return the configured records or raise the configured error.

        Args:
            name: FQDN.
            record_type: "MX" or "TXT".
        Returns:
            The records.
        """
        if self.error is not None:
            raise self.error
        return [
            DnsRecord(record_type, name, content, 1 if record_type == "MX" else None)
            for content in self.records_by_key.get((name, record_type), [])
        ]
