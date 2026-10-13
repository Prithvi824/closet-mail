"""Throttled owner notices (quota reached, reply rejected, ...) sent as system mail."""

# 3rd party imports
from redis.asyncio import Redis

# local imports
from mailalias.models import User
from mailalias.services.system_mail import SystemMailService


async def notify_owner(
    redis: Redis,
    system_mail: SystemMailService,
    owner: User,
    *,
    throttle_key: str,
    ttl_seconds: int,
    subject: str,
    body: str,
) -> bool:
    """Email the owner unless the same notice was sent within the throttle window.

    Args:
        redis, system_mail: Throttle store and mailer.
        owner: Recipient (their account email).
        throttle_key, ttl_seconds: Dedup key and window.
        subject, body: Notice content (never include correspondent addresses).
    Returns:
        True if a notice was sent.
    """
    if not await redis.set(f"notice:{throttle_key}", "1", nx=True, ex=ttl_seconds):
        return False
    await system_mail.send("notice", owner.email, subject=subject, body=body)
    return True
