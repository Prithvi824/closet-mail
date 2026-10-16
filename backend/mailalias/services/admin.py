"""Admin console logic: user management, system health and dead-letter queue recovery."""

# 1st party imports
import asyncio
import json
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

# 3rd party imports
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.errors import NotFound, ValidationFailed
from mailalias.config import Settings
from mailalias.integrations.cloudflare_queue import CloudflareQueueAdmin, MalformedJob, parse_job
from mailalias.mail.processor import HEARTBEAT_KEY
from mailalias.mail.types import RetryableError
from mailalias.models import Alias, AliasState, FailedDelivery, FailureKind, User, UserRole
from mailalias.security.sessions import SessionStore
from mailalias.services import audit, kv_sync
from mailalias.services.kv_sync import LAST_RECONCILE_KEY
from mailalias.services.quota import global_key

logger = logging.getLogger(__name__)

# users.limits keys an admin may override (see QuotaService / AliasService).
LIMIT_KEYS = frozenset({"forwards_per_hour", "replies_per_day", "alias_creates_per_hour"})
DLQ_BATCH = 100
DLQ_VISIBILITY_MS = 30_000
FAILURE_WINDOW_DAYS = 7


@dataclass(frozen=True)
class UserSummary:
    """A user row for the admin list."""

    user: User
    alias_count: int


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
    """Numbers for the admin health page; None means "could not be read"."""

    heartbeat_age_seconds: float | None
    inbound_backlog: int | None
    dlq_backlog: int | None
    sends_today: int
    send_cap: int
    hard_bounces_7d: int
    complaints_7d: int
    kv_reconcile: dict[str, Any] | None


class AdminService:
    """Operations behind /admin; every method assumes the caller is an admin."""

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

    async def list_users(self) -> list[UserSummary]:
        """All users with their live alias counts, oldest first.

        Returns:
            Summaries.
        """
        counts = (
            select(Alias.user_id, func.count().label("n"))
            .where(Alias.state.in_((AliasState.ACTIVE, AliasState.INACTIVE)))
            .group_by(Alias.user_id)
            .subquery()
        )
        rows = await self.db.execute(
            select(User, func.coalesce(counts.c.n, 0))
            .outerjoin(counts, counts.c.user_id == User.id)
            .order_by(User.created_at)
        )
        return [UserSummary(user, int(count)) for user, count in rows.all()]

    async def update_user(
        self,
        actor: User,
        user_id: uuid.UUID,
        *,
        disabled: bool | None = None,
        role: UserRole | None = None,
        limits: Mapping[str, int] | None = None,
        clear_limits: bool = False,
    ) -> UserSummary:
        """Disable/enable a user, change their role, or override their limits.

        Args:
            actor: The admin making the change (cannot disable or demote themselves).
            user_id: Target user.
            disabled, role: New values; None leaves them unchanged.
            limits: Limit overrides (keys from LIMIT_KEYS); clear_limits resets to defaults.
        Returns:
            The updated summary. Raises NotFound or ValidationFailed.
        """
        user = await self.db.get(User, user_id)
        if user is None:
            raise NotFound("User not found")
        if user.id == actor.id and (disabled or (role is not None and role != UserRole.ADMIN)):
            raise ValidationFailed("You cannot disable or demote your own account")
        if limits is not None:
            unknown = set(limits) - LIMIT_KEYS
            if unknown:
                raise ValidationFailed(f"Unknown limits: {', '.join(sorted(unknown))}")
            user.limits = {**(user.limits or {}), **limits}
        if clear_limits:
            user.limits = None
        if role is not None:
            user.role = role
        if disabled is not None and disabled != (user.disabled_at is not None):
            user.disabled_at = datetime.now(UTC) if disabled else None
            if disabled:
                await SessionStore(self.redis).delete_all_for_user(user.id)
            # The edge's subdomain catch-all flag depends on the account being enabled.
            kv_sync.mark_subdomain(self.db, user.id)
        await audit.record(
            self.db,
            "admin.user_update",
            actor_id=actor.id,
            target_type="user",
            target_id=str(user.id),
        )
        await self.db.flush()
        return next(s for s in await self.list_users() if s.user.id == user.id)

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
            actor: Admin (audited).
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
        await audit.record(self.db, "admin.dlq_retry", actor_id=actor.id, target_type="queue")
        return len(moved)
