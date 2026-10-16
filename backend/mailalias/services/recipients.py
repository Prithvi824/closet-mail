"""Recipients: add/verify/disable/delete forwarding addresses and manage PGP keys."""

# 1st party imports
import asyncio
import secrets
import uuid
from datetime import UTC, datetime, timedelta

# 3rd party imports
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.errors import Conflict, NotFound, QuotaExceeded, ValidationFailed
from mailalias.config import get_settings
from mailalias.integrations import gpg
from mailalias.mail.addresses import is_service_domain, normalize, split_address
from mailalias.models import Recipient, User
from mailalias.security.crypto import lookup_hash
from mailalias.services.system_mail import SystemMailService
from mailalias.services.users import token_digest

VERIFY_TTL = timedelta(hours=48)
VERIFY_RESEND_COOLDOWN = timedelta(minutes=5)
MAX_RECIPIENTS_PER_USER = 20


class RecipientService:
    """Recipient operations, always scoped to one owner."""

    def __init__(self, db: AsyncSession) -> None:
        """Build the service.

        Args:
            db: Database session.
        Returns:
            None.
        """
        self.db = db

    async def list_for(self, user: User) -> list[Recipient]:
        """All recipients of a user, oldest first.

        Args:
            user: Owner.
        Returns:
            Recipient rows.
        """
        query = select(Recipient).where(Recipient.user_id == user.id).order_by(Recipient.created_at)
        return list(await self.db.scalars(query))

    async def get_owned(self, user: User, recipient_id: uuid.UUID) -> Recipient:
        """Fetch a recipient that belongs to the user.

        Args:
            user: Owner.
            recipient_id: Recipient id.
        Returns:
            The recipient. Raises NotFound otherwise.
        """
        recipient = await self.db.get(Recipient, recipient_id)
        if recipient is None or recipient.user_id != user.id:
            raise NotFound("Recipient not found")
        return recipient

    async def add(self, user: User, email: str, mail: SystemMailService) -> Recipient:
        """Add an unverified recipient and email it a verification link.

        Args:
            user: Owner.
            email: Destination address.
            mail: System mail service.
        Returns:
            The new recipient. Raises Conflict for duplicates or too many recipients.
        """
        email = normalize(email)
        # Forwarding to our own addresses would loop mail through the service.
        if is_service_domain(split_address(email)[1], get_settings().alias_domain):
            raise ValidationFailed("Addresses on this service cannot be recipients")
        count = await self.db.scalar(
            select(func.count()).select_from(Recipient).where(Recipient.user_id == user.id)
        )
        if (count or 0) >= MAX_RECIPIENTS_PER_USER:
            raise Conflict(f"At most {MAX_RECIPIENTS_PER_USER} recipients are allowed")
        duplicate = await self.db.scalar(
            select(Recipient.id).where(
                Recipient.user_id == user.id, Recipient.email_hash == lookup_hash(email)
            )
        )
        if duplicate:
            raise Conflict("This recipient already exists")
        recipient = Recipient(user_id=user.id, email=email, email_hash=lookup_hash(email))
        self.db.add(recipient)
        await self.db.flush()
        await self.send_verification(recipient, mail)
        return recipient

    async def send_verification(self, recipient: Recipient, mail: SystemMailService) -> None:
        """Issue a fresh verification token and email the link.

        Args:
            recipient: Unverified recipient.
            mail: System mail service.
        Returns:
            None. Raises Conflict if already verified, QuotaExceeded if sent recently.
        """
        if recipient.verified_at is not None:
            raise Conflict("Recipient is already verified")
        if recipient.verify_sent_at is not None and (
            datetime.now(UTC) - recipient.verify_sent_at < VERIFY_RESEND_COOLDOWN
        ):
            raise QuotaExceeded("A verification email was sent recently. Try again shortly.")
        token = secrets.token_urlsafe(32)
        recipient.verify_token_hash = token_digest(token)
        recipient.verify_sent_at = datetime.now(UTC)
        await self.db.flush()
        link = mail.link(f"/api/v1/recipients/verify/{token}")
        await mail.send("verify_recipient", recipient.email, link=link)

    async def find_by_verify_token(self, token: str) -> Recipient | None:
        """Look up a pending recipient by an unexpired verification token.

        Args:
            token: Token from the link.
        Returns:
            The recipient, or None if unknown/expired.
        """
        recipient = await self.db.scalar(
            select(Recipient).where(Recipient.verify_token_hash == token_digest(token))
        )
        if recipient is None or recipient.verify_sent_at is None:
            return None
        if recipient.verify_sent_at + VERIFY_TTL < datetime.now(UTC):
            return None
        return recipient

    async def verify(self, token: str) -> Recipient | None:
        """Mark a recipient verified (single use).

        Args:
            token: Token from the link.
        Returns:
            The verified recipient, or None if the token is invalid/expired.
        """
        recipient = await self.find_by_verify_token(token)
        if recipient is None:
            return None
        recipient.verified_at = datetime.now(UTC)
        recipient.verify_token_hash = None
        await self.db.flush()
        return recipient

    async def _ensure_not_last_usable(self, user: User, recipient: Recipient) -> None:
        """Refuse to remove/disable the user's only usable recipient.

        Args:
            user: Owner.
            recipient: Recipient about to become unusable.
        Returns:
            None. Raises ValidationFailed.
        """
        if not recipient.is_usable:
            return
        others = [r for r in await self.list_for(user) if r.id != recipient.id and r.is_usable]
        if not others:
            raise ValidationFailed("You must keep at least one verified recipient")
        if user.default_recipient_id == recipient.id:
            user.default_recipient_id = others[0].id

    async def set_disabled(self, user: User, recipient_id: uuid.UUID, disabled: bool) -> Recipient:
        """Enable or disable forwarding to a recipient.

        Args:
            user: Owner.
            recipient_id: Recipient id.
            disabled: New state.
        Returns:
            The recipient.
        """
        recipient = await self.get_owned(user, recipient_id)
        if disabled and recipient.disabled_at is None:
            await self._ensure_not_last_usable(user, recipient)
            recipient.disabled_at = datetime.now(UTC)
        elif not disabled:
            recipient.disabled_at = None
            recipient.consecutive_hard_bounces = 0
        await self.db.flush()
        return recipient

    async def delete(self, user: User, recipient_id: uuid.UUID) -> None:
        """Delete a recipient (its alias links cascade).

        Args:
            user: Owner.
            recipient_id: Recipient id.
        Returns:
            None.
        """
        recipient = await self.get_owned(user, recipient_id)
        await self._ensure_not_last_usable(user, recipient)
        if user.default_recipient_id == recipient.id:
            user.default_recipient_id = None
        await self.db.flush()
        await self.db.delete(recipient)
        await self.db.flush()

    async def set_pgp(
        self,
        user: User,
        recipient_id: uuid.UUID,
        public_key: str | None,
        protect_subject: bool,
    ) -> Recipient:
        """Attach (or remove, when key is None) a PGP public key after validating it.

        Args:
            user: Owner.
            recipient_id: Recipient id.
            public_key: ASCII-armored public key, or None to remove.
            protect_subject: Hide the subject in forwarded encrypted mail.
        Returns:
            The recipient. Raises ValidationFailed for unusable keys.
        """
        recipient = await self.get_owned(user, recipient_id)
        if public_key is None or not public_key.strip():
            recipient.pgp_public_key = recipient.pgp_fingerprint = None
            recipient.pgp_protect_subject = False
            await self.db.flush()
            return recipient
        try:
            info = await asyncio.to_thread(gpg.inspect_key, public_key)
        except gpg.InvalidPgpKey as exc:
            raise ValidationFailed(str(exc), code="invalid_pgp_key") from exc
        # Check expiry first: gpg also drops the encrypt capability of expired keys.
        if info.expires_at is not None and info.expires_at <= datetime.now(UTC):
            raise ValidationFailed("Key has expired", code="invalid_pgp_key")
        if not info.can_encrypt:
            raise ValidationFailed("Key cannot be used for encryption", code="invalid_pgp_key")
        recipient.pgp_public_key = public_key.strip()
        recipient.pgp_fingerprint = info.fingerprint
        recipient.pgp_protect_subject = protect_subject
        await self.db.flush()
        return recipient
