"""Failed deliveries endpoint: recent bounces, complaints and delays for the user."""

# 3rd party imports
from fastapi import APIRouter

# local imports
from mailalias.api.deps import CurrentUser, DbSession, SystemMail
from mailalias.schemas.failed import FailedDeliveryResponse
from mailalias.services.failed_deliveries import FailedDeliveryService

router = APIRouter(prefix="/failed-deliveries", tags=["failed-deliveries"])


@router.get("")
async def list_failed(
    user: CurrentUser, db: DbSession, system_mail: SystemMail
) -> list[FailedDeliveryResponse]:
    """List recent delivery problems.

    Args:
        user, db, system_mail: Request dependencies.
    Returns:
        Up to 200 entries, newest first.
    """
    rows = await FailedDeliveryService(db, system_mail).list_for_user(user)
    return [FailedDeliveryResponse.build(*row) for row in rows]
