"""One subdomain's forwarding preferences and its activity."""

# 3rd party imports
from fastapi import APIRouter, Query

# local imports
from mailalias.api.deps import CurrentSubdomain, DbSession
from mailalias.schemas.me import SettingsUpdate, SubdomainSettings
from mailalias.schemas.metrics import SubdomainActivityResponse
from mailalias.services import kv_sync, metrics

router = APIRouter(tags=["subdomain"])


@router.get("/settings")
async def read_settings(user: CurrentSubdomain) -> SubdomainSettings:
    """The subdomain's forwarding preferences.

    Args:
        user: The subdomain.
    Returns:
        Its preferences.
    """
    return SubdomainSettings.model_validate(user)


@router.patch("/settings")
async def update_settings(
    body: SettingsUpdate, user: CurrentSubdomain, db: DbSession
) -> SubdomainSettings:
    """Update preferences; only fields present in the body change.

    Args:
        body: Partial settings.
        user: The subdomain.
        db: Database session.
    Returns:
        The updated preferences.
    """
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if value is not None:
            setattr(user, field, value)
    if "subdomain_catchall" in changes:
        kv_sync.mark_subdomain(db, user.id)
    await db.commit()
    return SubdomainSettings.model_validate(user)


@router.get("/activity")
async def get_activity(
    user: CurrentSubdomain,
    db: DbSession,
    days: int = Query(default=30, ge=1, le=metrics.MAX_DAYS),
    page: int = Query(default=1, ge=1),
) -> SubdomainActivityResponse:
    """Who sent what, when and to which inboxes, over the last `days` days.

    Args:
        user, db: The subdomain and the database session.
        days: Window (1-90 days, by received time).
        page: Page of recent mail (50 per page, newest first).
    Returns:
        The subdomain's activity.
    """
    return await metrics.subdomain_activity(db, user, days=days, page=page)
