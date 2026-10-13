"""Contact endpoints: list an alias's correspondents, start a conversation, block senders."""

# 1st party imports
import uuid

# 3rd party imports
from fastapi import APIRouter, Depends, status

# local imports
from mailalias.api.deps import AppSettings, CurrentUser, DbSession, token_scopes
from mailalias.api.errors import ValidationFailed
from mailalias.mail.addresses import is_service_domain, split_address
from mailalias.schemas.contacts import ContactCreate, ContactResponse, ContactUpdate
from mailalias.services.aliases import VISIBLE_STATES, AliasService
from mailalias.services.contacts import ContactService

router = APIRouter(
    tags=["contacts"], dependencies=[Depends(token_scopes("aliases:read", "contacts:write"))]
)


@router.get("/aliases/{alias_id}/contacts")
async def list_contacts(
    alias_id: uuid.UUID, user: CurrentUser, db: DbSession, settings: AppSettings
) -> list[ContactResponse]:
    """List an alias's contacts.

    Args:
        alias_id: Alias id.
        user: Authenticated user.
        db: Database session.
        settings: Settings (reply domain).
    Returns:
        Contacts, most recently seen first.
    """
    alias = await AliasService(db, settings).get_owned(user, alias_id)
    contacts = await ContactService(db).list_for_alias(alias)
    return [ContactResponse.build(c, settings.reply_domain) for c in contacts]


@router.post("/aliases/{alias_id}/contacts", status_code=status.HTTP_201_CREATED)
async def create_contact(
    alias_id: uuid.UUID,
    body: ContactCreate,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> ContactResponse:
    """Get or create a contact so the owner can write to someone new from the alias.

    Args:
        alias_id: Alias id.
        body: Correspondent address.
        user: Authenticated user.
        db: Database session.
        settings: Settings.
    Returns:
        The contact with its token address.
    """
    alias = await AliasService(db, settings).get_owned(user, alias_id)
    if alias.state not in VISIBLE_STATES:
        raise ValidationFailed("This alias is deleted")
    if is_service_domain(split_address(str(body.email))[1], settings.alias_domain):
        raise ValidationFailed("Addresses on this service cannot be contacts")
    contact = await ContactService(db).get_or_create(alias, str(body.email), None)
    await db.commit()
    return ContactResponse.build(contact, settings.reply_domain)


@router.patch("/contacts/{contact_id}")
async def update_contact(
    contact_id: uuid.UUID,
    body: ContactUpdate,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> ContactResponse:
    """Block or unblock a contact.

    Args:
        contact_id: Contact id.
        body: New blocked state.
        user: Authenticated user.
        db: Database session.
        settings: Settings.
    Returns:
        The contact.
    """
    contact = await ContactService(db).set_blocked(contact_id, user.id, body.blocked)
    await db.commit()
    return ContactResponse.build(contact, settings.reply_domain)
