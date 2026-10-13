"""Security audit trail writer."""

# 1st party imports
import uuid

# 3rd party imports
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.models import AuditLog


async def record(
    db: AsyncSession,
    action: str,
    *,
    user_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
) -> None:
    """Add an audit entry to the current transaction (the caller commits).

    Args:
        db: Database session.
        action: Event name, e.g. "login.success".
        user_id: Subject user.
        actor_id: Who performed it (defaults to the subject).
        target_type: Optional affected object type.
        target_id: Optional affected object id.
    Returns:
        None.
    """
    db.add(
        AuditLog(
            action=action,
            user_id=user_id,
            actor_id=actor_id or user_id,
            target_type=target_type,
            target_id=target_id,
        )
    )
