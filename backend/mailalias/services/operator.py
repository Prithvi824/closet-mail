"""Operator console logic: system health and dead-letter queue recovery."""

# 1st party imports
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

# 3rd party imports
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.config import Settings
from mailalias.integrations.cloudflare_queue import CloudflareQueueAdmin, MalformedJob, parse_job
from mailalias.mail.processor import HEARTBEAT_KEY
from mailalias.mail.types import RetryableError
from mailalias.models import FailedDelivery, FailureKind, User
from mailalias.services import audit
from mailalias.services.kv_sync import LAST_RECONCILE_KEY
from mailalias.services.quota import global_key

logger = logging.getLogger(__name__)

DLQ_BATCH = 100
DLQ_VISIBILITY_MS = 30_000
FAILURE_WINDOW_DAYS = 7


@dataclass(frozen=True)
class DlqItem:
    """Metadata of one dead-lettered job (never message content)."""

    lease_id: str
    r2_key: str
    rcpt_to: str
    raw_size: int
    received_at: datetime
    attempts: int


@dataclass(frozen=True)
class Health:
    """Numbers for the operator health page; None means "could not be read"."""

    heartbeat_age_seconds: float | None
    inbound_backlog: int | None
    dlq_backlog: int | None
    sends_today: int
    send_cap: int
    hard_bounces_7d: int
    complaints_7d: int
    kv_reconcile: dict[str, Any] | None


class OperatorService:
    """Operations behind /operator health and DLQ; the caller is the operator."""

    def __init__(self, db: AsyncSession, settings: Settings, redis: Redis) -> None:
        """Build the service.

        Args:
            db: Session (the caller commits).
            settings: Queue ids and the send cap.
            redis: Heartbeat, counters, sessions.
        Returns:
            None.
        """
        self.db = db
        self.settings = settings
        self.redis = redis

    async def health(self, queues: CloudflareQueueAdmin) -> Health:
        """Collect health numbers; a failing source yields None rather than an error.

        Args:
            queues: Cloudflare queue client.
        Returns:
            The snapshot.
        """
        heartbeat = await self.redis.get(HEARTBEAT_KEY)
        age = (
            (datetime.now(UTC) - datetime.fromisoformat(str(heartbeat))).total_seconds()
            if heartbeat
            else None
        )
        since = datetime.now(UTC) - timedelta(days=FAILURE_WINDOW_DAYS)
        failures = dict(
            (
                await self.db.execute(
                    select(FailedDelivery.kind, func.count())
                    .where(FailedDelivery.created_at >= since)
                    .group_by(FailedDelivery.kind)
                )
            ).all()
        )
        reconcile = await self.redis.get(LAST_RECONCILE_KEY)
        inbound, dlq = await asyncio.gather(
            self._backlog(queues, self.settings.cf_queue_id_inbound),
            self._backlog(queues, self.settings.cf_queue_id_dlq),
        )
        return Health(
            heartbeat_age_seconds=age,
            inbound_backlog=inbound,
            dlq_backlog=dlq,
            sends_today=int(await self.redis.get(global_key()) or 0),
            send_cap=self.settings.outbound_daily_cap,
            hard_bounces_7d=int(failures.get(FailureKind.HARD, 0)),
            complaints_7d=int(failures.get(FailureKind.COMPLAINT, 0)),
            kv_reconcile=json.loads(reconcile) if reconcile else None,
        )

    async def _backlog(self, queues: CloudflareQueueAdmin, queue_id: str) -> int | None:
        """Backlog of one queue, or None if Cloudflare cannot be reached.

        Args:
            queues: Queue client.
            queue_id: Queue id.
        Returns:
            Message count or None.
        """
        try:
            return (await queues.metrics(queue_id)).backlog_count
        except RetryableError as exc:
            logger.warning("queue metrics unavailable", extra={"error": str(exc)})
            return None

    async def dlq_items(self, queues: CloudflareQueueAdmin) -> list[DlqItem]:
        """Peek at dead-lettered jobs (leased for 30 s, then visible again).

        Args:
            queues: Queue client.
        Returns:
            Job metadata.
        """
        messages = await queues.pull(self.settings.cf_queue_id_dlq, DLQ_BATCH, DLQ_VISIBILITY_MS)
        items = []
        for message in messages:
            try:
                env = parse_job(message)
            except MalformedJob:
                continue
            items.append(
                DlqItem(
                    env.lease_id,
                    env.r2_key,
                    env.rcpt_to,
                    env.raw_size,
                    env.received_at,
                    env.attempts,
                )
            )
        return items

    async def dlq_retry(
        self, queues: CloudflareQueueAdmin, actor: User, r2_keys: list[str] | None
    ) -> int:
        """Move dead-lettered jobs back to the inbound queue (all, or those with these keys).

        Args:
            queues: Queue client.
            actor: Operator (audited).
            r2_keys: Jobs to move; None moves every job pulled.
        Returns:
            Number of jobs moved.
        """
        messages = await queues.pull(self.settings.cf_queue_id_dlq, DLQ_BATCH, DLQ_VISIBILITY_MS)
        moved: list[str] = []
        for message in messages:
            body = message.get("body")
            job = json.loads(body) if isinstance(body, str) else body
            if not isinstance(job, dict) or (
                r2_keys is not None and job.get("r2Key") not in r2_keys
            ):
                continue
            await queues.send(self.settings.cf_queue_id_inbound, job)
            # Ack right away: if a later send fails, only the jobs not yet moved stay behind.
            await queues.ack(self.settings.cf_queue_id_dlq, [str(message["lease_id"])])
            moved.append(str(message["lease_id"]))
        await audit.record(self.db, "operator.dlq_retry", actor_id=actor.id, target_type="queue")
        return len(moved)
