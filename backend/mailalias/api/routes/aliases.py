"""Alias endpoints (thin: validate, call AliasService, commit)."""

# 1st party imports
import uuid

# 3rd party imports
from fastapi import APIRouter, Depends, Query, status

# local imports
from mailalias.api.deps import AppSettings, CurrentUser, DbSession, token_scopes
from mailalias.db import get_redis
from mailalias.models import AliasState
from mailalias.schemas.aliases import (
    AliasBulk,
    AliasCreate,
    AliasPage,
    AliasResponse,
    AliasUpdate,
)
from mailalias.services.aliases import AliasService

router = APIRouter(
    prefix="/aliases",
    tags=["aliases"],
    dependencies=[Depends(token_scopes("aliases:read", "aliases:write"))],
)


@router.get("")
async def list_aliases(
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    q: str | None = Query(default=None, max_length=100),
    state: AliasState | None = None,
    label: uuid.UUID | None = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=100),
) -> AliasPage:
    """Search and page through the user's aliases.

    Args:
        user: Authenticated user.
        db: Database session.
        settings: App settings.
        q: Search text (address or description).
        state: State filter.
        label: Label filter.
        page: Page number.
        per_page: Page size.
    Returns:
        A page of aliases.
    """
    items, total = await AliasService(db, settings).list(
        user, query=q, state=state, label_id=label, page=page, per_page=per_page
    )
    return AliasPage(
        items=[AliasResponse.build(a) for a in items], total=total, page=page, per_page=per_page
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_alias(
    body: AliasCreate, user: CurrentUser, db: DbSession, settings: AppSettings
) -> AliasResponse:
    """Create an alias.

    Args:
        body: Creation options.
        user: Authenticated user.
        db: Database session.
        settings: App settings.
    Returns:
        The new alias.
    """
    alias = await AliasService(db, settings, get_redis()).create(
        user,
        alias_format=body.format,
        local_part=body.local_part,
        subdomain=body.subdomain,
        description=body.description,
        recipient_ids=body.recipient_ids,
        label_ids=body.label_ids,
    )
    await db.commit()
    return AliasResponse.build(alias)


@router.post("/bulk")
async def bulk_action(
    body: AliasBulk, user: CurrentUser, db: DbSession, settings: AppSettings
) -> dict[str, int]:
    """Activate, deactivate or delete many aliases.

    Args:
        body: Ids and action.
        user: Authenticated user.
        db: Database session.
        settings: App settings.
    Returns:
        {"changed": n}.
    """
    changed = await AliasService(db, settings).bulk(user, body.ids, body.action)
    await db.commit()
    return {"changed": changed}


@router.get("/{alias_id}")
async def get_alias(
    alias_id: uuid.UUID, user: CurrentUser, db: DbSession, settings: AppSettings
) -> AliasResponse:
    """Fetch one alias.

    Args:
        alias_id: Alias id.
        user: Authenticated user.
        db: Database session.
        settings: App settings.
    Returns:
        The alias.
    """
    return AliasResponse.build(await AliasService(db, settings).get_owned(user, alias_id))


@router.patch("/{alias_id}")
async def update_alias(
    alias_id: uuid.UUID,
    body: AliasUpdate,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> AliasResponse:
    """Update alias settings.

    Args:
        alias_id: Alias id.
        body: Fields to change.
        user: Authenticated user.
        db: Database session.
        settings: App settings.
    Returns:
        The updated alias.
    """
    fields = body.model_fields_set
    alias = await AliasService(db, settings).update(
        user,
        alias_id,
        description=body.description,
        clear_description="description" in fields and body.description is None,
        reply_enabled=body.reply_enabled,
        active=body.active,
        recipient_ids=body.recipient_ids,
        label_ids=body.label_ids,
    )
    await db.commit()
    return AliasResponse.build(alias)


@router.delete("/{alias_id}")
async def delete_alias(
    alias_id: uuid.UUID, user: CurrentUser, db: DbSession, settings: AppSettings
) -> AliasResponse:
    """Soft-delete an alias (restorable for 30 days).

    Args:
        alias_id: Alias id.
        user: Authenticated user.
        db: Database session.
        settings: App settings.
    Returns:
        The deleted alias.
    """
    alias = await AliasService(db, settings).delete(user, alias_id)
    await db.commit()
    return AliasResponse.build(alias)


@router.post("/{alias_id}/restore")
async def restore_alias(
    alias_id: uuid.UUID, user: CurrentUser, db: DbSession, settings: AppSettings
) -> AliasResponse:
    """Restore a deleted alias (comes back inactive).

    Args:
        alias_id: Alias id.
        user: Authenticated user.
        db: Database session.
        settings: App settings.
    Returns:
        The restored alias.
    """
    alias = await AliasService(db, settings).restore(user, alias_id)
    await db.commit()
    return AliasResponse.build(alias)


@router.post("/{alias_id}/forget", status_code=status.HTTP_204_NO_CONTENT)
async def forget_alias(
    alias_id: uuid.UUID, user: CurrentUser, db: DbSession, settings: AppSettings
) -> None:
    """Permanently detach an alias; its address can never be reused.

    Args:
        alias_id: Alias id.
        user: Authenticated user.
        db: Database session.
        settings: App settings.
    Returns:
        None (204).
    """
    await AliasService(db, settings).forget(user, alias_id)
    await db.commit()
