"""Reusable in-memory fakes for external services."""

# 1st party imports
from collections.abc import AsyncIterator


class FakeKv:
    """Dict-backed stand-in for CloudflareKv."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        """Create the store.

        Args:
            initial: Starting keys.
        Returns:
            None.
        """
        self.data: dict[str, str] = dict(initial or {})

    async def put(self, key: str, value: str) -> None:
        """Set a key.

        Args:
            key: Key.
            value: Value.
        Returns:
            None.
        """
        self.data[key] = value

    async def delete(self, key: str) -> None:
        """Remove a key if present.

        Args:
            key: Key.
        Returns:
            None.
        """
        self.data.pop(key, None)

    async def bulk_put(self, items: dict[str, str]) -> None:
        """Set many keys.

        Args:
            items: Key/value pairs.
        Returns:
            None.
        """
        self.data.update(items)

    async def bulk_delete(self, keys: list[str]) -> None:
        """Remove many keys.

        Args:
            keys: Keys.
        Returns:
            None.
        """
        for key in keys:
            self.data.pop(key, None)

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
