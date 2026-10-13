"""Workers KV client used by KvSync to publish alias/token validity to the edge."""

# 1st party imports
from collections.abc import AsyncIterator
from urllib.parse import quote

# local imports
from mailalias.integrations.cloudflare_api import CloudflareApi

BULK_LIMIT = 10_000
LIST_PAGE_SIZE = 1000


class CloudflareKv:
    """Read/write access to one KV namespace."""

    def __init__(self, api: CloudflareApi, namespace_id: str) -> None:
        """Build the client.

        Args:
            api: Cloudflare API client.
            namespace_id: KV namespace id (CF_KV_NAMESPACE_ID).
        Returns:
            None.
        """
        self._api = api
        self._base = api.account_path(f"/storage/kv/namespaces/{namespace_id}")

    def _value_url(self, key: str) -> str:
        """URL for a single key (keys contain "@" and ":" so are fully escaped).

        Args:
            key: KV key.
        Returns:
            The value endpoint URL.
        """
        return f"{self._base}/values/{quote(key, safe='')}"

    async def put(self, key: str, value: str) -> None:
        """Write one key.

        Args:
            key: KV key.
            value: Value text.
        Returns:
            None.
        """
        await self._api.json(
            "kv.put",
            "PUT",
            self._value_url(key),
            content=value.encode(),
            headers={"Content-Type": "text/plain"},
        )

    async def delete(self, key: str) -> None:
        """Delete one key (missing keys are fine).

        Args:
            key: KV key.
        Returns:
            None.
        """
        await self._api.json("kv.delete", "DELETE", self._value_url(key))

    async def bulk_put(self, items: dict[str, str]) -> None:
        """Write many keys, chunked to the API limit.

        Args:
            items: Mapping of key to value.
        Returns:
            None.
        """
        pairs = [{"key": key, "value": value} for key, value in items.items()]
        for start in range(0, len(pairs), BULK_LIMIT):
            await self._api.json(
                "kv.bulk_put", "PUT", f"{self._base}/bulk", json=pairs[start : start + BULK_LIMIT]
            )

    async def bulk_delete(self, keys: list[str]) -> None:
        """Delete many keys, chunked to the API limit.

        Args:
            keys: Keys to delete.
        Returns:
            None.
        """
        for start in range(0, len(keys), BULK_LIMIT):
            await self._api.json(
                "kv.bulk_delete",
                "POST",
                f"{self._base}/bulk/delete",
                json=keys[start : start + BULK_LIMIT],
            )

    async def list_keys(self, prefix: str) -> AsyncIterator[str]:
        """Iterate over all key names with a prefix, following cursors.

        Args:
            prefix: Key prefix, e.g. "a:".
        Returns:
            An async iterator of key names.
        """
        cursor: str | None = None
        while True:
            params = {"prefix": prefix, "limit": LIST_PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            payload = await self._api.json("kv.list", "GET", f"{self._base}/keys", params=params)
            for item in payload.get("result") or []:
                yield str(item["name"])
            cursor = (payload.get("result_info") or {}).get("cursor") or None
            if not cursor:
                return
