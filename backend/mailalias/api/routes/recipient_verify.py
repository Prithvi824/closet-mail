"""Inbox verification links: public pages; the emailed token is the credential."""

# 3rd party imports
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

# local imports
from mailalias.api.deps import DbSession
from mailalias.api.html import simple_page
from mailalias.services.recipients import RecipientService

router = APIRouter(prefix="/recipients", tags=["recipients"])


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
