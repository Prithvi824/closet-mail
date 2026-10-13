"""One-click actions from the forward banner: block a sender, disable an alias.

The signed link is the credential. GET only shows a confirmation page (mail scanners prefetch
links); POST performs the action.
"""

# 1st party imports
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

# 3rd party imports
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.deps import AppSettings, DbSession
from mailalias.api.errors import DomainError
from mailalias.api.html import simple_page
from mailalias.config import Settings
from mailalias.models import Alias, Contact, User
from mailalias.security.signing import InvalidActionToken, load_action
from mailalias.services.aliases import VISIBLE_STATES, AliasService
from mailalias.services.contacts import ContactService

router = APIRouter(prefix="/a", tags=["actions"])

INVALID = ("Link expired", "This link is invalid or has expired.")


async def _block_contact(
    db: AsyncSession, settings: Settings, user: User, target: uuid.UUID
) -> str:
    """Block the contact so its mail is no longer forwarded.

    Args:
        db, settings: Session and settings.
        user: Owner.
        target: Contact id.
    Returns:
        Result message.
    """
    await ContactService(db).set_blocked(target, user.id, True)
    return "This sender is blocked. You can unblock it from the dashboard."


async def _disable_alias(
    db: AsyncSession, settings: Settings, user: User, target: uuid.UUID
) -> str:
    """Deactivate the alias (mail to it is accepted and dropped).

    Args:
        db, settings: Session and settings.
        user: Owner.
        target: Alias id.
    Returns:
        Result message.
    """
    alias = await AliasService(db, settings).update(user, target, active=False)
    return f"{alias.address} is disabled. You can turn it back on from the dashboard."


Handler = Callable[[AsyncSession, Settings, User, uuid.UUID], Awaitable[str]]
ACTIONS: dict[str, tuple[str, str, Handler]] = {
    "block_contact": ("Block this sender?", "Block sender", _block_contact),
    "disable_alias": ("Disable this alias?", "Disable alias", _disable_alias),
}


async def _resolve(db: AsyncSession, signed: str) -> tuple[str, User, uuid.UUID] | None:
    """Verify the link and check the user and target still exist and belong together.

    Args:
        db: Session.
        signed: Signed token from the URL.
    Returns:
        (action, owner, target id), or None if the link is unusable.
    """
    try:
        payload: dict[str, Any] = load_action(signed)
        action, target, user_id = payload["a"], uuid.UUID(payload["id"]), uuid.UUID(payload["uid"])
    except (InvalidActionToken, KeyError, TypeError, ValueError):
        return None
    user = await db.get(User, user_id)
    if action not in ACTIONS or user is None or user.disabled_at is not None:
        return None
    if action == "block_contact":
        contact = await db.get(Contact, target)
        alias = await db.get(Alias, contact.alias_id) if contact else None
        owned = alias is not None and alias.user_id == user.id
    else:
        alias = await db.get(Alias, target)
        owned = alias is not None and alias.user_id == user.id and alias.state in VISIBLE_STATES
    return (action, user, target) if owned else None


@router.get("/{signed}", response_class=HTMLResponse)
async def confirm_action(signed: str, db: DbSession) -> HTMLResponse:
    """Show what the link will do, with a button. Never changes state.

    Args:
        signed: Signed action token.
        db: Session.
    Returns:
        Confirmation page or an error page.
    """
    resolved = await _resolve(db, signed)
    if resolved is None:
        return simple_page(*INVALID, status_code=404)
    title, button, _ = ACTIONS[resolved[0]]
    return simple_page(title, "Confirm to continue.", button=button)


@router.post("/{signed}", response_class=HTMLResponse)
async def perform_action(signed: str, db: DbSession, settings: AppSettings) -> HTMLResponse:
    """Perform the action the link was signed for.

    Args:
        signed: Signed action token.
        db, settings: Request dependencies.
    Returns:
        Result page or an error page.
    """
    resolved = await _resolve(db, signed)
    if resolved is None:
        return simple_page(*INVALID, status_code=404)
    action, user, target = resolved
    try:
        message = await ACTIONS[action][2](db, settings, user, target)
    except DomainError as exc:
        return simple_page("Not possible", exc.message, status_code=409)
    await db.commit()
    return simple_page("Done", message)
