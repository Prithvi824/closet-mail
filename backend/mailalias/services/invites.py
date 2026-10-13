"""Admin-issued invitations and their acceptance."""

# 1st party imports
import secrets
import uuid
from datetime import UTC, datetime, timedelta

# 3rd party imports
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.errors import Conflict, NotFound
from mailalias.mail.addresses import normalize
from mailalias.models import Invite, User
from mailalias.security.crypto import lookup_hash
from mailalias.services import audit
from mailalias.services.system_mail import SystemMailService
from mailalias.services.users import UserService, token_digest

INVITE_TTL = timedelta(days=7)


class InviteService:
    """Create, list and accept invites."""

    def __init__(self, db: AsyncSession) -> None:
        """Build the service.

        Args:
            db: Database session.
        Returns:
            None.
        """
        self.db = db

    async def create(self, email: str, invited_by: User, mail: SystemMailService) -> Invite:
        """Create an invite and email its link.

        Args:
            email: Invitee address.
            invited_by: Admin creating it.
            mail: System mail service.
        Returns:
            The invite (flushed).
        """
        email = normalize(email)
        if await UserService(self.db).get_by_email(email):
            raise Conflict("An account with this email already exists")
        token = secrets.token_urlsafe(32)
        invite = Invite(
            email=email,
            email_hash=lookup_hash(email),
            token_hash=token_digest(token),
            invited_by=invited_by.id,
            expires_at=datetime.now(UTC) + INVITE_TTL,
        )
        self.db.add(invite)
        await self.db.flush()
        await audit.record(
            self.db,
            "invite.created",
            actor_id=invited_by.id,
            target_type="invite",
            target_id=str(invite.id),
        )
        await mail.send("invite", email, link=mail.link(f"/invite/{token}"))
        return invite

    async def list_all(self) -> list[Invite]:
        """All invites, newest first.

        Returns:
            Invite rows.
        """
        return list(await self.db.scalars(select(Invite).order_by(Invite.created_at.desc())))

    async def accept(self, token: str, username: str, password: str) -> User:
        """Redeem an invite: create the account with its email as a verified recipient.

        Args:
            token: Token from the invite link.
            username: Chosen username.
            password: Chosen password.
        Returns:
            The new user. Raises NotFound for invalid, used or expired invites.
        """
        invite = await self.db.scalar(
            select(Invite).where(Invite.token_hash == token_digest(token)).with_for_update()
        )
        if invite is None or invite.used_at is not None or invite.expires_at < datetime.now(UTC):
            raise NotFound("Invite is invalid or expired", code="invalid_invite")
        user = await UserService(self.db).create_user(username, invite.email, password)
        invite.used_at = datetime.now(UTC)
        await audit.record(
            self.db,
            "invite.accepted",
            user_id=user.id,
            target_type="invite",
            target_id=str(invite.id),
        )
        await self.db.flush()
        return user

    async def get(self, invite_id: uuid.UUID) -> Invite:
        """Fetch one invite.

        Args:
            invite_id: Invite id.
        Returns:
            The invite. Raises NotFound.
        """
        invite = await self.db.get(Invite, invite_id)
        if invite is None:
            raise NotFound("Invite not found")
        return invite
