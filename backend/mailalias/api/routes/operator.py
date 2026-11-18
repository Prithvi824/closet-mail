"""Operator console endpoints: subdomains, health and DLQ. Operator session; no API tokens."""

# 3rd party imports
from fastapi import APIRouter, status
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.deps import AppSettings, DbSession, Operator, QueueAdmin, SystemMail
from mailalias.config import Settings
from mailalias.db import get_redis
from mailalias.models import User
from mailalias.schemas.operator import DlqItemResponse, DlqRetryRequest, HealthResponse
from mailalias.schemas.subdomains import SubdomainCreate, SubdomainResponse, SubdomainUpdate
from mailalias.services.operator import OperatorService
from mailalias.services.subdomains import SubdomainService, build_responses

router = APIRouter(prefix="/operator", tags=["operator"])


async def _one(db: AsyncSession, settings: Settings, user: User) -> SubdomainResponse:
    """Describe one subdomain.

    Args:
        db, settings: Session and settings.
        user: The subdomain.
    Returns:
        Its response model.
    """
    (response,) = await build_responses(db, get_redis(), settings, [user])
    return response


@router.get("/subdomains")
async def list_subdomains(
    operator: Operator, db: DbSession, settings: AppSettings
) -> list[SubdomainResponse]:
    """Every subdomain with its counts and status, the operator's own first.

    Args:
        operator, db, settings: Request dependencies.
    Returns:
        The subdomains.
    """
    users = await SubdomainService(db, settings).list()
    return await build_responses(db, get_redis(), settings, users)


@router.post("/subdomains", status_code=status.HTTP_201_CREATED)
async def create_subdomain(
    body: SubdomainCreate,
    operator: Operator,
    db: DbSession,
    settings: AppSettings,
    mail: SystemMail,
) -> SubdomainResponse:
    """Create a subdomain; its first inbox is emailed a verification link.

    Args:
        body: Label, display name, first inbox and notes.
        operator, db, settings, mail: Request dependencies.
    Returns:
        The new subdomain.
    """
    user = await SubdomainService(db, settings).create(
        label=body.label,
        display_name=body.display_name,
        inbox_email=str(body.inbox_email),
        notes=body.notes,
        mail=mail,
        actor=operator,
    )
    await db.commit()
    return await _one(db, settings, user)


@router.get("/subdomains/{label}")
async def get_subdomain(
    label: str, operator: Operator, db: DbSession, settings: AppSettings
) -> SubdomainResponse:
    """One subdomain.

    Args:
        label: Subdomain label.
        operator, db, settings: Request dependencies.
    Returns:
        The subdomain.
    """
    return await _one(db, settings, await SubdomainService(db, settings).get(label))


@router.patch("/subdomains/{label}")
async def update_subdomain(
    label: str, body: SubdomainUpdate, operator: Operator, db: DbSession, settings: AppSettings
) -> SubdomainResponse:
    """Edit name, notes or limits, or suspend/resume.

    Args:
        label: Subdomain label.
        body: Fields to change.
        operator, db, settings: Request dependencies.
    Returns:
        The updated subdomain.
    """
    user = await SubdomainService(db, settings).update(
        label,
        display_name=body.display_name,
        notes=body.notes,
        suspended=body.suspended,
        limits=body.limits,
        clear_limits=body.clear_limits,
        actor=operator,
    )
    await db.commit()
    return await _one(db, settings, user)


@router.post("/subdomains/{label}/retire")
async def retire_subdomain(
    label: str, operator: Operator, db: DbSession, settings: AppSettings
) -> SubdomainResponse:
    """Retire a subdomain: aliases forgotten (addresses stay reserved), inboxes disabled.

    Args:
        label: Subdomain label.
        operator, db, settings: Request dependencies.
    Returns:
        The retired subdomain.
    """
    user = await SubdomainService(db, settings).retire(label, actor=operator)
    await db.commit()
    return await _one(db, settings, user)


@router.get("/health")
async def health(
    operator: Operator, db: DbSession, settings: AppSettings, queues: QueueAdmin
) -> HealthResponse:
    """Processor heartbeat, queue backlogs, today's sends, bounces and KV reconcile state.

    Args:
        operator, db, settings, queues: Request dependencies.
    Returns:
        The health snapshot.
    """
    return HealthResponse.build(await OperatorService(db, settings, get_redis()).health(queues))


@router.get("/dlq")
async def list_dlq(
    operator: Operator, db: DbSession, settings: AppSettings, queues: QueueAdmin
) -> list[DlqItemResponse]:
    """Peek at dead-lettered jobs (metadata only; they stay in the DLQ).

    Args:
        operator, db, settings, queues: Request dependencies.
    Returns:
        Job metadata.
    """
    items = await OperatorService(db, settings, get_redis()).dlq_items(queues)
    return [DlqItemResponse.build(item) for item in items]


@router.post("/dlq/retry")
async def retry_dlq(
    body: DlqRetryRequest,
    operator: Operator,
    db: DbSession,
    settings: AppSettings,
    queues: QueueAdmin,
) -> dict[str, int]:
    """Move dead-lettered jobs back to the inbound queue.

    Args:
        body: Optional r2 keys to move (default: all).
        operator, db, settings, queues: Request dependencies.
    Returns:
        {"moved": n}.
    """
    moved = await OperatorService(db, settings, get_redis()).dlq_retry(
        queues, operator, body.r2_keys
    )
    await db.commit()
    return {"moved": moved}
