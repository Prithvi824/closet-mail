"""Throttled notices (quota reached, reply rejected, ...) to the operator and, when it helps,
to the subdomain's own inboxes. Sent as system mail; they never use a subdomain's send share."""

# 1st party imports
from collections.abc import Sequence

# 3rd party imports
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.models import Recipient, User, UserRole
from mailalias.services.system_mail import SystemMailService


async def operator_addresses(db: AsyncSession) -> list[str]:
    """Email addresses of the enabled operator account(s).

    Args:
        db: Session.
    Returns:
        Addresses (empty if no operator has an email).
    """
    operators = await db.scalars(
        select(User).where(User.role == UserRole.ADMIN, User.disabled_at.is_(None))
    )
    return [user.email for user in operators if user.email]


async def subdomain_inboxes(db: AsyncSession, user: User) -> list[str]:
    """The subdomain's usable (verified, enabled) inbox addresses.

    Args:
        db: Session.
        user: The subdomain.
    Returns:
        Addresses.
    """
    recipients = await db.scalars(
        select(Recipient).where(Recipient.user_id == user.id).order_by(Recipient.created_at)
    )
    return [r.email for r in recipients if r.is_usable]


async def send_notice(
    redis: Redis,
    system_mail: SystemMailService,
    to: Sequence[str],
    *,
    throttle_key: str,
    ttl_seconds: int,
    subject: str,
    body: str,
) -> bool:
    """Mail a notice to each address, unless the same notice went out within the window.

    Args:
        redis, system_mail: Throttle store and mailer.
        to: Addresses (one message each, so nobody sees the others).
        throttle_key, ttl_seconds: Dedup key and window.
        subject, body: Notice content (never include correspondent addresses).
    Returns:
        True if a notice was sent.
    """
    addresses = list(dict.fromkeys(to))
    if not addresses:
        return False
    if not await redis.set(f"notice:{throttle_key}", "1", nx=True, ex=ttl_seconds):
        return False
    for address in addresses:
        await system_mail.send("notice", address, subject=subject, body=body)
    return True
