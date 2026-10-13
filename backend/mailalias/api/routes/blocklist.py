"""Blocklist endpoints: list, add and remove blocked sender addresses and domains."""

# 1st party imports
import uuid

# 3rd party imports
from fastapi import APIRouter, Response, status

# local imports
from mailalias.api.deps import CurrentUser, DbSession
from mailalias.schemas.blocklist import BlocklistCreate, BlocklistResponse
from mailalias.services.blocklist import BlocklistService

router = APIRouter(prefix="/blocklist", tags=["blocklist"])


@router.get("")
async def list_blocklist(user: CurrentUser, db: DbSession) -> list[BlocklistResponse]:
    """List blocked senders.

    Args:
        user, db: Request dependencies.
    Returns:
        Entries, newest first.
    """
    return [BlocklistResponse.build(e) for e in await BlocklistService(db).list(user)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_blocklist(
    body: BlocklistCreate, user: CurrentUser, db: DbSession
) -> BlocklistResponse:
    """Block an address or domain.

    Args:
        body: Pattern.
        user, db: Request dependencies.
    Returns:
        The new entry.
    """
    entry = await BlocklistService(db).add(user, body.pattern)
    await db.commit()
    return BlocklistResponse.build(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blocklist(entry_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    """Unblock.

    Args:
        entry_id: Entry id.
        user, db: Request dependencies.
    Returns:
        204 No Content.
    """
    await BlocklistService(db).delete(user, entry_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
