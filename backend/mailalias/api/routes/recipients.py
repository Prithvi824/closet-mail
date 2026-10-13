"""Recipient management and the email verification link."""

# 1st party imports
import uuid

# 3rd party imports
from fastapi import APIRouter, Depends, status
from fastapi.responses import HTMLResponse

# local imports
from mailalias.api.deps import CurrentUser, DbSession, SystemMail, token_scopes
from mailalias.api.html import simple_page
from mailalias.schemas.recipients import (
    PgpKeyUpdate,
    RecipientCreate,
    RecipientResponse,
    RecipientUpdate,
)
from mailalias.services.recipients import RecipientService

router = APIRouter(prefix="/recipients", tags=["recipients"])
VERIFY_PATH_PREFIX = "/api/v1/recipients/verify/"


@router.get("", dependencies=[Depends(token_scopes("recipients:read"))])
async def list_recipients(user: CurrentUser, db: DbSession) -> list[RecipientResponse]:
    """List the user's recipients.

    Args:
        user: Authenticated user.
        db: Database session.
    Returns:
        Recipients, oldest first.
    """
    recipients = await RecipientService(db).list_for(user)
    return [RecipientResponse.build(r, user.default_recipient_id) for r in recipients]


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_recipient(
    body: RecipientCreate, user: CurrentUser, db: DbSession, mail: SystemMail
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
    recipient = await RecipientService(db).add(user, str(body.email), mail)
    await db.commit()
    return RecipientResponse.build(recipient, user.default_recipient_id)


@router.patch("/{recipient_id}")
async def update_recipient(
    recipient_id: uuid.UUID, body: RecipientUpdate, user: CurrentUser, db: DbSession
) -> RecipientResponse:
    """Enable or disable a recipient.

    Args:
        recipient_id: Recipient id.
        body: New disabled state.
        user: Authenticated user.
        db: Database session.
    Returns:
        The updated recipient.
    """
    recipient = await RecipientService(db).set_disabled(user, recipient_id, body.disabled)
    await db.commit()
    return RecipientResponse.build(recipient, user.default_recipient_id)


@router.delete("/{recipient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recipient(recipient_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
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
    recipient_id: uuid.UUID, user: CurrentUser, db: DbSession, mail: SystemMail
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
    await service.send_verification(await service.get_owned(user, recipient_id), mail)
    await db.commit()
    return {"status": "sent"}


@router.put("/{recipient_id}/pgp")
async def set_pgp_key(
    recipient_id: uuid.UUID, body: PgpKeyUpdate, user: CurrentUser, db: DbSession
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
    return RecipientResponse.build(recipient, user.default_recipient_id)


@router.get("/verify/{token}", response_class=HTMLResponse)
async def verify_page(token: str, db: DbSession) -> HTMLResponse:
    """Show a confirmation page. GET never changes state (mail scanners prefetch links).

    Args:
        token: Verification token.
        db: Database session.
    Returns:
        HTML page with a confirm button, or an error page.
    """
    if await RecipientService(db).find_by_verify_token(token) is None:
        return simple_page(
            "Link expired", "This verification link is invalid or has expired.", status_code=404
        )
    return simple_page(
        "Confirm forwarding address",
        "Confirm that mail from your aliases may be forwarded to this address.",
        button="Confirm address",
    )


@router.post("/verify/{token}", response_class=HTMLResponse)
async def verify_confirm(token: str, db: DbSession) -> HTMLResponse:
    """Verify the recipient (token is the credential; exempt from the CSRF header).

    Args:
        token: Verification token.
        db: Database session.
    Returns:
        HTML result page.
    """
    recipient = await RecipientService(db).verify(token)
    await db.commit()
    if recipient is None:
        return simple_page(
            "Link expired", "This verification link is invalid or has expired.", status_code=404
        )
    return simple_page("Address confirmed", "Mail can now be forwarded to this address.")
