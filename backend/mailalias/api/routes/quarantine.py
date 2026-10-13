"""Quarantine endpoints: list held messages, release them to the inbox, or delete them."""

# 1st party imports
import uuid

# 3rd party imports
from fastapi import APIRouter, Response, status

# local imports
from mailalias.api.deps import AppSettings, CurrentUser, DbSession, Storage
from mailalias.schemas.quarantine import QuarantineResponse, ReleaseResponse
from mailalias.services.quarantine import QuarantineService

router = APIRouter(prefix="/quarantine", tags=["quarantine"])


@router.get("")
async def list_quarantine(
    user: CurrentUser, db: DbSession, settings: AppSettings, storage: Storage
) -> list[QuarantineResponse]:
    """List pending quarantined messages.

    Args:
        user, db, settings, storage: Request dependencies.
    Returns:
        Held messages, newest first.
    """
    items = await QuarantineService(db, settings, storage).list_for_user(user)
    return [QuarantineResponse.build(item, address) for item, address in items]


@router.post("/{item_id}/release", status_code=status.HTTP_202_ACCEPTED)
async def release_quarantined(
    item_id: uuid.UUID, user: CurrentUser, db: DbSession, settings: AppSettings, storage: Storage
) -> ReleaseResponse:
    """Queue delivery of a held message (the spam check is skipped).

    Args:
        item_id: Item id.
        user, db, settings, storage: Request dependencies.
    Returns:
        Accepted.
    """
    await QuarantineService(db, settings, storage).request_release(user, item_id)
    return ReleaseResponse()


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quarantined(
    item_id: uuid.UUID, user: CurrentUser, db: DbSession, settings: AppSettings, storage: Storage
) -> Response:
    """Delete a held message for good.

    Args:
        item_id: Item id.
        user, db, settings, storage: Request dependencies.
    Returns:
        204 No Content.
    """
    await QuarantineService(db, settings, storage).delete(user, item_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
