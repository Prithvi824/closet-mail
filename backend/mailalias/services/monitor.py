"""Health monitor: turn bad health numbers into admin email alerts (deduplicated for 6 hours)."""

# 1st party imports
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# 3rd party imports
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.config import Settings
from mailalias.integrations.cloudflare_queue import CloudflareQueueAdmin
from mailalias.mail.types import MailKind, Outcome
from mailalias.models import FailedDelivery, FailureKind, MailLog, User, UserRole
from mailalias.services.admin import AdminService
from mailalias.services.system_mail import SystemMailService

logger = logging.getLogger(__name__)

HEARTBEAT_STALE_SECONDS = 300
SEND_CAP_WARN_RATIO = 0.8
BOUNCE_RATE_LIMIT = 0.05
ALERT_DEDUP_SECONDS = 6 * 3600


@dataclass(frozen=True)
class Alert:
    """One problem worth an email; `key` deduplicates repeats."""

    key: str
    subject: str
    body: str


async def bounce_rate_24h(db: AsyncSession) -> tuple[int, int]:
    """Hard bounces and delivered sends over the last 24 hours.

    Args:
        db: Session.
    Returns:
        (hard bounces, delivered forwards + replies).
    """
    since = datetime.now(UTC) - timedelta(hours=24)
    bounces = await db.scalar(
        select(func.count())
        .select_from(FailedDelivery)
        .where(FailedDelivery.kind == FailureKind.HARD, FailedDelivery.created_at >= since)
    )
    sends = await db.scalar(
        select(func.count())
        .select_from(MailLog)
        .where(
            MailLog.outcome == Outcome.DELIVERED,
            MailLog.kind.in_((MailKind.FORWARD, MailKind.REPLY)),
            MailLog.created_at >= since,
        )
    )
    return int(bounces or 0), int(sends or 0)


async def collect_alerts(
    db: AsyncSession, settings: Settings, redis: Redis, queues: CloudflareQueueAdmin
) -> list[Alert]:
    """Check processor liveness, the DLQ, the send cap and the bounce rate.

    Args:
        db: Session.
        settings: Settings.
        redis: Redis.
        queues: Cloudflare queue client.
    Returns:
        Current alerts (may be empty).
    """
    health = await AdminService(db, settings, redis).health(queues)
    alerts: list[Alert] = []
    age = health.heartbeat_age_seconds
    if age is None or age > HEARTBEAT_STALE_SECONDS:
        seen = "never" if age is None else f"{int(age // 60)} minutes ago"
        alerts.append(
            Alert(
                "processor_down",
                "Mail processor is not running",
                f"The mail processor last reported {seen}. Incoming mail waits in the Cloudflare "
                "queue, which keeps jobs for only one day: restart the processor container soon.",
            )
        )
    if health.dlq_backlog:
        alerts.append(
            Alert(
                "dlq",
                f"{health.dlq_backlog} message(s) in the dead-letter queue",
                "Jobs failed 5 times and moved to the dead-letter queue, which keeps them for one "
                "day. Fix the cause, then use Admin → Health → Retry.",
            )
        )
    if health.sends_today >= health.send_cap * SEND_CAP_WARN_RATIO:
        alerts.append(
            Alert(
                "send_cap",
                "Daily send cap almost reached",
                f"{health.sends_today} of {health.send_cap} messages sent today. When the cap is "
                "reached, forwards wait in the queue until the next UTC day.",
            )
        )
    bounces, sends = await bounce_rate_24h(db)
    if bounces and bounces > sends * BOUNCE_RATE_LIMIT:
        alerts.append(
            Alert(
                "bounce_rate",
                "High bounce rate",
                f"{bounces} hard bounces against {sends} delivered messages in the last 24 hours. "
                "A high bounce rate can get the sending account suspended.",
            )
        )
    return alerts


async def send_alerts(
    db: AsyncSession, redis: Redis, system_mail: SystemMailService, alerts: list[Alert]
) -> int:
    """Email every enabled admin about each alert not already sent in the last 6 hours.

    Args:
        db: Session.
        redis: Dedup store.
        system_mail: Mailer.
        alerts: Alerts to send.
    Returns:
        Number of alerts emailed.
    """
    if not alerts:
        return 0
    admins = [
        admin
        for admin in await db.scalars(select(User).where(User.role == UserRole.ADMIN))
        if admin.disabled_at is None
    ]
    sent = 0
    for alert in alerts:
        if not await redis.set(f"alert:{alert.key}", "1", nx=True, ex=ALERT_DEDUP_SECONDS):
            continue
        for admin in admins:
            await system_mail.send("notice", admin.email, subject=alert.subject, body=alert.body)
        logger.warning("alert sent", extra={"alert": alert.key, "admins": len(admins)})
        sent += 1
    return sent
