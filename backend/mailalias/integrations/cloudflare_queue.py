"""Inbound mail source: Cloudflare Queue (HTTP pull) for jobs plus R2 for raw messages."""

# 1st party imports
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

# local imports
from mailalias.integrations.cloudflare_api import CloudflareApi
from mailalias.integrations.r2 import R2Storage
from mailalias.mail.types import InboundEnvelope

logger = logging.getLogger(__name__)

JOB_VERSION = 1


class InboxSource(Protocol):
    """Where the processor gets inbound mail from (interface contract)."""

    async def pull(self, batch_size: int, visibility_timeout_ms: int) -> list[InboundEnvelope]:
        """Lease up to `batch_size` jobs."""
        ...

    async def fetch_raw(self, r2_key: str) -> bytes:
        """Download the raw message for a job."""
        ...

    async def ack(self, lease_ids: list[str]) -> None:
        """Mark jobs done."""
        ...

    async def retry(self, lease_ids: list[str], delay_seconds: int) -> None:
        """Return jobs to the queue after a delay."""
        ...

    async def delete_raw(self, r2_key: str) -> None:
        """Delete the raw message once handled."""
        ...


class MalformedJob(ValueError):
    """A queue message whose body is not a valid v1 InboundJob."""


def parse_job(message: dict[str, Any]) -> InboundEnvelope:
    """Convert one pulled queue message into an InboundEnvelope.

    Args:
        message: Item of result.messages from the pull API (body is a JSON string).
    Returns:
        The envelope. Raises MalformedJob if the body is invalid.
    """
    try:
        body = message["body"]
        job = json.loads(body) if isinstance(body, str) else body
        if job.get("v") != JOB_VERSION:
            raise MalformedJob(f"unsupported job version {job.get('v')!r}")
        return InboundEnvelope(
            lease_id=str(message["lease_id"]),
            attempts=int(message.get("attempts", 0)),
            r2_key=str(job["r2Key"]),
            mail_from=str(job["mailFrom"]).lower(),
            rcpt_to=str(job["rcptTo"]).lower(),
            raw_size=int(job["rawSize"]),
            received_at=datetime.fromisoformat(job["receivedAt"].replace("Z", "+00:00")),
        )
    except MalformedJob:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise MalformedJob(type(exc).__name__) from exc


class CloudflareQueueInbox:
    """InboxSource backed by the `mail-inbound` queue and the `mail-inbox` bucket."""

    def __init__(self, api: CloudflareApi, storage: R2Storage, queue_id: str) -> None:
        """Build the inbox.

        Args:
            api: Cloudflare API client.
            storage: R2 storage for raw messages.
            queue_id: Queue id (CF_QUEUE_ID_INBOUND).
        Returns:
            None.
        """
        self._api = api
        self._storage = storage
        self._messages_url = api.account_path(f"/queues/{queue_id}/messages")

    async def pull(self, batch_size: int, visibility_timeout_ms: int) -> list[InboundEnvelope]:
        """Lease jobs; malformed ones are acked immediately and skipped.

        Args:
            batch_size: Maximum jobs to lease.
            visibility_timeout_ms: Lease duration.
        Returns:
            Valid envelopes, possibly empty.
        """
        payload = await self._api.json(
            "queue.pull",
            "POST",
            f"{self._messages_url}/pull",
            json={"batch_size": batch_size, "visibility_timeout_ms": visibility_timeout_ms},
        )
        messages = (payload.get("result") or {}).get("messages") or []
        envelopes: list[InboundEnvelope] = []
        malformed: list[str] = []
        for message in messages:
            try:
                envelopes.append(parse_job(message))
            except MalformedJob as exc:
                logger.error(
                    "malformed job skipped", extra={"msg_id": message.get("id"), "error": str(exc)}
                )
                if message.get("lease_id"):
                    malformed.append(str(message["lease_id"]))
        if malformed:
            await self.ack(malformed)
        return envelopes

    async def fetch_raw(self, r2_key: str) -> bytes:
        """Download a raw message.

        Args:
            r2_key: Key from the job.
        Returns:
            Raw RFC 5322 bytes. Raises R2ObjectMissing or RetryableError.
        """
        return await self._storage.get(r2_key)

    async def ack(self, lease_ids: list[str]) -> None:
        """Acknowledge jobs so they are not redelivered.

        Args:
            lease_ids: Leases to ack.
        Returns:
            None.
        """
        await self._send_ack([{"lease_id": lease} for lease in lease_ids], [])

    async def retry(self, lease_ids: list[str], delay_seconds: int) -> None:
        """Return jobs to the queue for redelivery after a delay.

        Args:
            lease_ids: Leases to retry.
            delay_seconds: Redelivery delay.
        Returns:
            None.
        """
        retries = [{"lease_id": lease, "delay_seconds": delay_seconds} for lease in lease_ids]
        await self._send_ack([], retries)

    async def delete_raw(self, r2_key: str) -> None:
        """Delete a raw message from R2.

        Args:
            r2_key: Key from the job.
        Returns:
            None.
        """
        await self._storage.delete(r2_key)

    async def _send_ack(self, acks: list[dict[str, Any]], retries: list[dict[str, Any]]) -> None:
        """Call the ack endpoint when there is something to send.

        Args:
            acks: Ack entries.
            retries: Retry entries.
        Returns:
            None.
        """
        if acks or retries:
            await self._api.json(
                "queue.ack",
                "POST",
                f"{self._messages_url}/ack",
                json={"acks": acks, "retries": retries},
            )


@dataclass(frozen=True)
class QueueMetrics:
    """Backlog of one queue."""

    backlog_count: int
    oldest_message_ms: int  # epoch ms of the oldest message; 0 when empty


class CloudflareQueueAdmin:
    """Queue operations for the admin console: metrics, and moving DLQ jobs back."""

    def __init__(self, api: CloudflareApi) -> None:
        """Build the client.

        Args:
            api: Cloudflare API client.
        Returns:
            None.
        """
        self._api = api

    def _url(self, queue_id: str, suffix: str = "") -> str:
        """Account-scoped URL of a queue endpoint.

        Args:
            queue_id: Queue id.
            suffix: Path after the queue id.
        Returns:
            The URL.
        """
        return self._api.account_path(f"/queues/{queue_id}{suffix}")

    async def metrics(self, queue_id: str) -> QueueMetrics:
        """Current backlog.

        Args:
            queue_id: Queue id.
        Returns:
            The metrics.
        """
        payload = await self._api.json("queue.metrics", "GET", self._url(queue_id, "/metrics"))
        result = payload.get("result") or {}
        return QueueMetrics(
            int(result.get("backlog_count", 0)), int(result.get("oldest_message_timestamp_ms", 0))
        )

    async def pull(
        self, queue_id: str, batch_size: int, visibility_timeout_ms: int
    ) -> list[dict[str, Any]]:
        """Lease raw messages (bodies are not parsed).

        Args:
            queue_id: Queue id.
            batch_size: Maximum messages.
            visibility_timeout_ms: Lease duration.
        Returns:
            Messages as returned by the API.
        """
        payload = await self._api.json(
            "queue.pull",
            "POST",
            self._url(queue_id, "/messages/pull"),
            json={"batch_size": batch_size, "visibility_timeout_ms": visibility_timeout_ms},
        )
        return list((payload.get("result") or {}).get("messages") or [])

    async def send(self, queue_id: str, body: dict[str, Any]) -> None:
        """Push one JSON message.

        Args:
            queue_id: Queue id.
            body: Message body.
        Returns:
            None.
        """
        await self._api.json(
            "queue.send",
            "POST",
            self._url(queue_id, "/messages"),
            json={"body": body, "content_type": "json"},
        )

    async def ack(self, queue_id: str, lease_ids: list[str]) -> None:
        """Acknowledge (remove) leased messages.

        Args:
            queue_id: Queue id.
            lease_ids: Leases.
        Returns:
            None.
        """
        if lease_ids:
            await self._api.json(
                "queue.ack",
                "POST",
                self._url(queue_id, "/messages/ack"),
                json={"acks": [{"lease_id": lease} for lease in lease_ids], "retries": []},
            )
