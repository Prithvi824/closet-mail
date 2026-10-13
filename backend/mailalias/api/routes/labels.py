"""Label endpoints."""

# 1st party imports
import uuid

# 3rd party imports
from fastapi import APIRouter, Depends, status

# local imports
from mailalias.api.deps import CurrentUser, DbSession, token_scopes
from mailalias.schemas.labels import LabelCreate, LabelResponse, LabelUpdate
from mailalias.services.labels import LabelService

router = APIRouter(
    prefix="/labels",
    tags=["labels"],
    dependencies=[Depends(token_scopes("aliases:read", "aliases:write"))],
)


@router.get("")
async def list_labels(user: CurrentUser, db: DbSession) -> list[LabelResponse]:
    """List the user's labels.

    Args:
        user: Authenticated user.
        db: Database session.
    Returns:
        Labels by name.
    """
    return [LabelResponse.model_validate(lb) for lb in await LabelService(db).list_for(user)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_label(body: LabelCreate, user: CurrentUser, db: DbSession) -> LabelResponse:
    """Create a label.

    Args:
        body: Name and colour.
        user: Authenticated user.
        db: Database session.
    Returns:
        The label.
    """
    label = await LabelService(db).create(user, body.name, body.color)
    await db.commit()
    return LabelResponse.model_validate(label)


@router.patch("/{label_id}")
async def update_label(
    label_id: uuid.UUID, body: LabelUpdate, user: CurrentUser, db: DbSession
) -> LabelResponse:
    """Rename or recolour a label.

    Args:
        label_id: Label id.
        body: Changes.
        user: Authenticated user.
        db: Database session.
    Returns:
        The label.
    """
    label = await LabelService(db).update(user, label_id, body.name, body.color)
    await db.commit()
    return LabelResponse.model_validate(label)


@router.delete("/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_label(label_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    """Delete a label.

    Args:
        label_id: Label id.
        user: Authenticated user.
        db: Database session.
    Returns:
        None (204).
    """
    await LabelService(db).delete(user, label_id)
    await db.commit()
