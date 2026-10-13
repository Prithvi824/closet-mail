"""Admin console endpoints (users, invites, health). Admin session required; no API tokens."""

# 1st party imports
import uuid

# 3rd party imports
from fastapi import APIRouter, status

# local imports
from mailalias.api.deps import AdminUser, AppSettings, DbSession, QueueAdmin, SystemMail
from mailalias.db import get_redis
from mailalias.schemas.admin import (
    AdminUserResponse,
    AdminUserUpdate,
    DlqItemResponse,
    DlqRetryRequest,
    HealthResponse,
)
from mailalias.schemas.auth import InviteCreate
from mailalias.schemas.me import InviteResponse
from mailalias.services.admin import AdminService
from mailalias.services.invites import InviteService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/invites")
async def list_invites(admin: AdminUser, db: DbSession) -> list[InviteResponse]:
    """List all invites.

    Args:
        admin: Admin user.
        db: Database session.
    Returns:
        Invites, newest first.
    """
    return [InviteResponse.model_validate(i) for i in await InviteService(db).list_all()]


@router.post("/invites", status_code=status.HTTP_201_CREATED)
async def create_invite(
    body: InviteCreate, admin: AdminUser, db: DbSession, mail: SystemMail
) -> InviteResponse:
    """Invite an email address; the link is emailed to it.

    Args:
        body: Invitee email.
        admin: Admin user.
        db: Database session.
        mail: System mail service.
    Returns:
        The created invite.
    """
    invite = await InviteService(db).create(str(body.email), admin, mail)
    await db.commit()
    return InviteResponse.model_validate(invite)


@router.get("/users")
async def list_users(
    admin: AdminUser, db: DbSession, settings: AppSettings
) -> list[AdminUserResponse]:
    """List every user with their alias count.

    Args:
        admin, db, settings: Request dependencies.
    Returns:
        Users, oldest first.
    """
    service = AdminService(db, settings, get_redis())
    return [AdminUserResponse.build(summary) for summary in await service.list_users()]


@router.patch("/users/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    body: AdminUserUpdate,
    admin: AdminUser,
    db: DbSession,
    settings: AppSettings,
) -> AdminUserResponse:
    """Disable/enable a user, change their role or override their limits.

    Args:
        user_id: Target user.
        body: Changes (`limits: null` resets to defaults).
        admin, db, settings: Request dependencies.
    Returns:
        The updated user.
    """
    fields = body.model_fields_set
    summary = await AdminService(db, settings, get_redis()).update_user(
        admin,
        user_id,
        disabled=body.disabled,
        role=body.role,
        limits=body.limits,
        clear_limits="limits" in fields and body.limits is None,
    )
    await db.commit()
    return AdminUserResponse.build(summary)


@router.get("/health")
async def health(
    admin: AdminUser, db: DbSession, settings: AppSettings, queues: QueueAdmin
) -> HealthResponse:
    """Processor heartbeat, queue backlogs, today's sends, bounces and KV reconcile state.

    Args:
        admin, db, settings, queues: Request dependencies.
    Returns:
        The health snapshot.
    """
    return HealthResponse.build(await AdminService(db, settings, get_redis()).health(queues))


@router.get("/dlq")
async def list_dlq(
    admin: AdminUser, db: DbSession, settings: AppSettings, queues: QueueAdmin
) -> list[DlqItemResponse]:
    """Peek at dead-lettered jobs (metadata only; they stay in the DLQ).

    Args:
        admin, db, settings, queues: Request dependencies.
    Returns:
        Job metadata.
    """
    items = await AdminService(db, settings, get_redis()).dlq_items(queues)
    return [DlqItemResponse.build(item) for item in items]


@router.post("/dlq/retry")
async def retry_dlq(
    body: DlqRetryRequest,
    admin: AdminUser,
    db: DbSession,
    settings: AppSettings,
    queues: QueueAdmin,
) -> dict[str, int]:
    """Move dead-lettered jobs back to the inbound queue.

    Args:
        body: Optional r2 keys to move (default: all).
        admin, db, settings, queues: Request dependencies.
    Returns:
        {"moved": n}.
    """
    moved = await AdminService(db, settings, get_redis()).dlq_retry(queues, admin, body.r2_keys)
    await db.commit()
    return {"moved": moved}
