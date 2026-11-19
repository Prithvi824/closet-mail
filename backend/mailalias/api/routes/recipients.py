"""Recipient (inbox) management inside one subdomain."""

# 1st party imports
import uuid
from datetime import UTC, datetime

# 3rd party imports
from fastapi import APIRouter, Depends, status

# local imports
from mailalias.api.deps import CurrentSubdomain, DbSession, SystemMail, token_scopes
from mailalias.api.errors import QuotaExceeded
from mailalias.db import get_redis
from mailalias.schemas.recipients import (
    PgpKeyUpdate,
    RecipientCreate,
    RecipientResponse,
    RecipientUpdate,
)
from mailalias.services.recipients import RecipientService

# Verification emails share the global outbound cap with forwards, so each user gets a small budget.
VERIFY_MAILS_PER_DAY = 10

router = APIRouter(prefix="/recipients", tags=["recipients"])


async def _spend_verification_mail(user: CurrentSubdomain) -> None:
    """Count one verification email against the user's daily budget.

    Args:
        user: Authenticated user.
    Returns:
        None. Raises QuotaExceeded once the daily budget is spent.
    """
    redis = get_redis()
    key = f"q:verify:{user.id}:{datetime.now(UTC):%Y%m%d}"
    sent = await redis.incr(key)
    if sent == 1:
        await redis.expire(key, 86400)
    if sent > VERIFY_MAILS_PER_DAY:
        raise QuotaExceeded("Too many verification emails today. Try again tomorrow.")


@router.get("", dependencies=[Depends(token_scopes("recipients:read"))])
async def list_recipients(user: CurrentSubdomain, db: DbSession) -> list[RecipientResponse]:
    """List the user's recipients.

    Args:
        user: Authenticated user.
        db: Database session.
    Returns:
        Recipients, oldest first.
    """
    recipients = await RecipientService(db).list_for(user)
    return [RecipientResponse.build(r) for r in recipients]


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_recipient(
    body: RecipientCreate, user: CurrentSubdomain, db: DbSession, mail: SystemMail
) -> RecipientResponse:
    """Add a recipient and send its verification email.

    Args:
        body: Address to add.
        user: Authenticated user.
        db: Database session.
        mail: System mail service.
    Returns:
        The new (unverified) recipient.
    """
    await _spend_verification_mail(user)
    recipient = await RecipientService(db).add(user, str(body.email), mail)
    await db.commit()
    return RecipientResponse.build(recipient)


@router.patch("/{recipient_id}")
async def update_recipient(
    recipient_id: uuid.UUID, body: RecipientUpdate, user: CurrentSubdomain, db: DbSession
) -> RecipientResponse:
    """Enable/disable a recipient or change whether it is a default inbox.

    Args:
        recipient_id: Recipient id.
        body: Fields to change.
        user: Authenticated user.
        db: Database session.
    Returns:
        The updated recipient.
    """
    service = RecipientService(db)
    recipient = await service.get_owned(user, recipient_id)
    if body.forward_by_default is not None:
        recipient = await service.set_default(user, recipient_id, body.forward_by_default)
    if body.disabled is not None:
        recipient = await service.set_disabled(user, recipient_id, body.disabled)
    await db.commit()
    return RecipientResponse.build(recipient)


@router.delete("/{recipient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recipient(recipient_id: uuid.UUID, user: CurrentSubdomain, db: DbSession) -> None:
    """Delete a recipient.

    Args:
        recipient_id: Recipient id.
        user: Authenticated user.
        db: Database session.
    Returns:
        None (204).
    """
    await RecipientService(db).delete(user, recipient_id)
    await db.commit()


@router.post("/{recipient_id}/resend-verification", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(
    recipient_id: uuid.UUID, user: CurrentSubdomain, db: DbSession, mail: SystemMail
) -> dict[str, str]:
    """Send a new verification email.

    Args:
        recipient_id: Recipient id.
        user: Authenticated user.
        db: Database session.
        mail: System mail service.
    Returns:
        Acknowledgement.
    """
    service = RecipientService(db)
    recipient = await service.get_owned(user, recipient_id)
    await _spend_verification_mail(user)
    await service.send_verification(recipient, mail)
    await db.commit()
    return {"status": "sent"}


@router.put("/{recipient_id}/pgp")
async def set_pgp_key(
    recipient_id: uuid.UUID, body: PgpKeyUpdate, user: CurrentSubdomain, db: DbSession
) -> RecipientResponse:
    """Set or clear the recipient's PGP public key.

    Args:
        recipient_id: Recipient id.
        body: Key (null clears) and subject protection flag.
        user: Authenticated user.
        db: Database session.
    Returns:
        The updated recipient.
    """
    recipient = await RecipientService(db).set_pgp(
        user, recipient_id, body.public_key, body.protect_subject
    )
    await db.commit()
    return RecipientResponse.build(recipient)
