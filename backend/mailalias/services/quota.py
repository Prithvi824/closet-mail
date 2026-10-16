"""Send quotas: the global provider cap and per-user forward/reply limits (Redis counters)."""

# 1st party imports
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

# 3rd party imports
from redis.asyncio import Redis

# local imports
from mailalias.config import Settings

DAY_TTL_SECONDS = 2 * 86_400
HOUR_TTL_SECONDS = 2 * 3_600
QuotaKind = Literal["forward", "reply"]
# users.limits keys that override the Settings defaults.
LIMIT_KEYS = {"forward": "forwards_per_hour", "reply": "replies_per_day"}
# Cloudflare Queues accepts retry delays of at most 12 hours.
MAX_RETRY_DELAY_SECONDS = 43_200


def cap_retry_delay(now: datetime | None = None) -> int:
    """Seconds to wait before retrying mail held by the global daily cap.

    Args:
        now: Current time (defaults to now, UTC).
    Returns:
        Seconds until just after the next UTC midnight, capped at the queue's maximum delay.
    """
    now = now or datetime.now(UTC)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return min(int((midnight - now).total_seconds()) + 60, MAX_RETRY_DELAY_SECONDS)


def global_key(now: datetime | None = None) -> str:
    """Redis key of today's global send counter (UTC day).

    Args:
        now: Override for tests.
    Returns:
        The key "q:global:YYYYMMDD".
    """
    return f"q:global:{(now or datetime.now(UTC)):%Y%m%d}"


def user_key(user_id: uuid.UUID, kind: QuotaKind, now: datetime | None = None) -> str:
    """Redis key of a user's current forward (hourly) or reply (daily) counter.

    Args:
        user_id: User id.
        kind: "forward" or "reply".
        now: Override for tests.
    Returns:
        "q:fwd:<user>:<YYYYMMDDHH>" or "q:rep:<user>:<YYYYMMDD>".
    """
    now = now or datetime.now(UTC)
    if kind == "forward":
        return f"q:fwd:{user_id}:{now:%Y%m%d%H}"
    return f"q:rep:{user_id}:{now:%Y%m%d}"


class QuotaService:
    """Checks and consumes send quotas atomically."""

    def __init__(self, redis: Redis, settings: Settings) -> None:
        """Build the service.

        Args:
            redis: Redis client.
            settings: Limits.
        Returns:
            None.
        """
        self.redis = redis
        self.settings = settings

    async def _consume(self, key: str, limit: int, cost: int, ttl: int) -> bool:
        """Add `cost` to a counter unless that would exceed `limit`.

        Args:
            key: Counter key.
            limit: Maximum allowed value.
            cost: Units to consume.
            ttl: Expiry for a new counter.
        Returns:
            True if consumed; False (and unchanged) if over the limit.
        """
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.incrby(key, cost)
            pipe.expire(key, ttl, nx=True)
            value, _ = await pipe.execute()
        if value > limit:
            await self.redis.decrby(key, cost)
            return False
        return True

    async def global_send_allowed(self, cost: int = 1) -> bool:
        """Consume from the daily provider cap (OUTBOUND_DAILY_CAP).

        Args:
            cost: Messages about to be sent.
        Returns:
            True if sending is allowed.
        """
        return await self._consume(
            global_key(), self.settings.outbound_daily_cap, cost, DAY_TTL_SECONDS
        )

    async def global_sent_today(self) -> int:
        """Messages counted against today's global cap.

        Returns:
            The count.
        """
        return int(await self.redis.get(global_key()) or 0)

    async def refund_global(self, cost: int = 1) -> None:
        """Return units to today's cap after a send that did not happen.

        Args:
            cost: Units to give back.
        Returns:
            None.
        """
        await self.redis.decrby(global_key(), cost)

    def user_limit(self, kind: QuotaKind, limits: Mapping[str, Any] | None = None) -> int:
        """Effective per-user limit: users.limits override, else the Settings default.

        Args:
            kind: "forward" or "reply".
            limits: The user's `limits` JSON, if any.
        Returns:
            The limit.
        """
        override = (limits or {}).get(LIMIT_KEYS[kind])
        if isinstance(override, int) and override >= 0:
            return override
        if kind == "forward":
            return self.settings.user_forwards_per_hour
        return self.settings.user_replies_per_day

    async def check_and_consume(
        self,
        user_id: uuid.UUID,
        kind: QuotaKind,
        cost: int = 1,
        *,
        limits: Mapping[str, Any] | None = None,
    ) -> bool:
        """Consume from a user's forward (per hour) or reply (per day) quota.

        Args:
            user_id: User id.
            kind: "forward" or "reply".
            cost: Messages about to be sent.
            limits: The user's `limits` JSON (overrides defaults).
        Returns:
            True if allowed (and consumed); False if over the limit.
        """
        ttl = HOUR_TTL_SECONDS if kind == "forward" else DAY_TTL_SECONDS
        return await self._consume(
            user_key(user_id, kind), self.user_limit(kind, limits), cost, ttl
        )

    async def refund_user(self, user_id: uuid.UUID, kind: QuotaKind, cost: int = 1) -> None:
        """Give back per-user units after a send that did not happen.

        Args:
            user_id: User id.
            kind: "forward" or "reply".
            cost: Units.
        Returns:
            None.
        """
        await self.redis.decrby(user_key(user_id, kind), cost)
