"""Passkeys as a second factor: registration, listing, removal and login verification."""

# 1st party imports
import uuid
from datetime import UTC, datetime

# 3rd party imports
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.errors import Conflict, NotFound, Unauthorized, ValidationFailed
from mailalias.config import Settings
from mailalias.models import User, WebAuthnCredential
from mailalias.security import webauthn as passkey
from mailalias.security.sessions import SessionData, SessionStore
from mailalias.services import audit

MAX_PASSKEYS = 10


async def has_passkeys(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Whether the user registered any passkey (then login needs a second factor).

    Args:
        db: Session.
        user_id: User.
    Returns:
        True if at least one exists.
    """
    count = await db.scalar(
        select(func.count())
        .select_from(WebAuthnCredential)
        .where(WebAuthnCredential.user_id == user_id)
    )
    return bool(count)


class PasskeyService:
    """Ceremonies keep their challenge in the server-side session (one at a time)."""

    def __init__(self, db: AsyncSession, settings: Settings, sessions: SessionStore) -> None:
        """Build the service.

        Args:
            db: Session (the caller commits).
            settings: APP_BASE_URL (relying party).
            sessions: Session store (challenges).
        Returns:
            None.
        """
        self.db = db
        self.rp = passkey.relying_party(settings)
        self.sessions = sessions

    async def list(self, user: User) -> list[WebAuthnCredential]:
        """The user's passkeys, oldest first.

        Args:
            user: Owner.
        Returns:
            Credentials.
        """
        query = (
            select(WebAuthnCredential)
            .where(WebAuthnCredential.user_id == user.id)
            .order_by(WebAuthnCredential.created_at)
        )
        return list(await self.db.scalars(query))

    async def _take_challenge(self, sid: str, data: SessionData) -> str:
        """Read and clear the pending challenge (each challenge is single-use).

        Args:
            sid, data: Current session.
        Returns:
            The challenge. Raises ValidationFailed when none is pending.
        """
        challenge = data.webauthn_challenge
        if not challenge:
            raise ValidationFailed("Start again: no passkey request is pending")
        data.webauthn_challenge = None
        await self.sessions.save(sid, data)
        return challenge

    async def begin_registration(self, user: User, sid: str, data: SessionData) -> str:
        """Create registration options and remember the challenge.

        Args:
            user: Signed-in user.
            sid, data: Current session.
        Returns:
            Options JSON for the browser.
        """
        existing = [credential.credential_id for credential in await self.list(user)]
        if len(existing) >= MAX_PASSKEYS:
            raise ValidationFailed(f"At most {MAX_PASSKEYS} passkeys")
        options, challenge = passkey.registration_options(
            self.rp, user.id.bytes, user.username, existing
        )
        data.webauthn_challenge = challenge
        await self.sessions.save(sid, data)
        return options

    async def finish_registration(
        self, user: User, sid: str, data: SessionData, name: str, response_json: str
    ) -> WebAuthnCredential:
        """Verify the authenticator's response and store the passkey.

        Args:
            user: Signed-in user.
            sid, data: Current session.
            name: Label, e.g. "Laptop".
            response_json: PublicKeyCredential JSON.
        Returns:
            The stored credential. Raises ValidationFailed or Conflict.
        """
        challenge = await self._take_challenge(sid, data)
        try:
            verified = passkey.verify_registration(self.rp, response_json, challenge)
        except passkey.PasskeyError as exc:
            raise ValidationFailed("The passkey could not be verified") from exc
        credential = WebAuthnCredential(
            user_id=user.id,
            credential_id=verified.credential_id,
            public_key=verified.public_key,
            sign_count=verified.sign_count,
            name=name.strip() or "Passkey",
        )
        try:
            async with self.db.begin_nested():
                self.db.add(credential)
        except IntegrityError as exc:
            raise Conflict("This passkey is already registered") from exc
        await audit.record(
            self.db,
            "passkey.add",
            user_id=user.id,
            target_type="passkey",
            target_id=str(credential.id),
        )
        return credential

    async def delete(self, user: User, credential_id: uuid.UUID) -> None:
        """Remove a passkey.

        Args:
            user: Owner.
            credential_id: Row id.
        Returns:
            None. Raises NotFound.
        """
        credential = await self.db.get(WebAuthnCredential, credential_id)
        if credential is None or credential.user_id != user.id:
            raise NotFound("Passkey not found")
        await self.db.delete(credential)
        await audit.record(
            self.db,
            "passkey.remove",
            user_id=user.id,
            target_type="passkey",
            target_id=str(credential_id),
        )

    async def begin_authentication(self, user: User, sid: str, data: SessionData) -> str:
        """Authentication options for an MFA-pending login.

        Args:
            user: User who passed the password step.
            sid, data: MFA-pending session.
        Returns:
            Options JSON. Raises ValidationFailed when the user has no passkeys.
        """
        allowed = [credential.credential_id for credential in await self.list(user)]
        if not allowed:
            raise ValidationFailed("No passkeys registered")
        options, challenge = passkey.authentication_options(self.rp, allowed)
        data.webauthn_challenge = challenge
        await self.sessions.save(sid, data)
        return options

    async def finish_authentication(
        self, user: User, sid: str, data: SessionData, response_json: str
    ) -> None:
        """Verify the assertion; on success the session's second factor is satisfied.

        Args:
            user: User who passed the password step.
            sid, data: MFA-pending session.
            response_json: PublicKeyCredential JSON.
        Returns:
            None. Raises Unauthorized when verification fails.
        """
        challenge = await self._take_challenge(sid, data)
        try:
            claimed = passkey.credential_id_of(response_json)
        except passkey.PasskeyError as exc:
            raise Unauthorized("Passkey sign-in failed", code="invalid_passkey") from exc
        credential = await self.db.scalar(
            select(WebAuthnCredential).where(
                WebAuthnCredential.credential_id == claimed, WebAuthnCredential.user_id == user.id
            )
        )
        if credential is None:
            raise Unauthorized("Passkey sign-in failed", code="invalid_passkey")
        try:
            credential.sign_count = passkey.verify_authentication(
                self.rp, response_json, challenge, credential.public_key, credential.sign_count
            )
        except passkey.PasskeyError as exc:
            await audit.record(self.db, "login.mfa_failed", user_id=user.id)
            raise Unauthorized("Passkey sign-in failed", code="invalid_passkey") from exc
        credential.last_used_at = datetime.now(UTC)
        data.mfa_passed = True
        await self.sessions.save(sid, data)
        await audit.record(self.db, "login.success", user_id=user.id)
