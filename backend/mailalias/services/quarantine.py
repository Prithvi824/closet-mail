"""Quarantine: hold suspected spam encrypted in R2, list it, release it or delete it."""

# 1st party imports
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

# 3rd party imports
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.errors import Conflict, NotFound
from mailalias.config import Settings
from mailalias.integrations.r2 import ObjectStore, R2ObjectMissing
from mailalias.mail.types import HandlerResult, InboundEnvelope, Outcome
from mailalias.models import Alias, QuarantineItem, User
from mailalias.security.crypto import decrypt_bytes, encrypt_bytes
from mailalias.services import task_dispatch

KEY_PREFIX = "quarantine/"
RELEASE_TASK = "quarantine.release"

# Runs the forward path for a released message (ForwardHandler.handle with the spam check off).
ReleaseForwarder = Callable[[InboundEnvelope, bytes], Awaitable[HandlerResult]]


class QuarantineService:
    """Quarantine rows in Postgres; the raw message is Fernet-encrypted in R2."""

    def __init__(self, db: AsyncSession, settings: Settings, storage: ObjectStore) -> None:
        """Build the service.

        Args:
            db: Session (the caller commits).
            settings: quarantine_days.
            storage: Object store holding the encrypted raw messages.
        Returns:
            None.
        """
        self.db = db
        self.settings = settings
        self.storage = storage

    async def hold(
        self,
        *,
        raw: bytes,
        alias: Alias,
        contact_id: uuid.UUID | None,
        sender: str,
        subject: str | None,
        score: float,
    ) -> QuarantineItem:
        """Store the encrypted message and add its row.

        Args:
            raw: Raw message bytes.
            alias: Alias it was sent to (must have an owner).
            contact_id: Contact, if known.
            sender, subject: Shown to the owner (encrypted columns).
            score: Spam score.
        Returns:
            The new row (flushed, not committed).
        """
        assert alias.user_id is not None
        key = f"{KEY_PREFIX}{uuid.uuid4()}.bin"
        await self.storage.put(key, encrypt_bytes(raw))
        item = QuarantineItem(
            user_id=alias.user_id,
            alias_id=alias.id,
            contact_id=contact_id,
            r2_key=key,
            spam_score=score,
            sender=sender,
            subject=subject,
            expires_at=datetime.now(UTC) + timedelta(days=self.settings.quarantine_days),
        )
        self.db.add(item)
        await self.db.flush()
        return item

    async def list_for_user(self, user: User) -> list[tuple[QuarantineItem, str | None]]:
        """Pending (unreleased, unexpired) items with their alias address, newest first.

        Args:
            user: Owner.
        Returns:
            (item, alias address) pairs.
        """
        query = (
            select(QuarantineItem, Alias.address)
            .outerjoin(Alias, Alias.id == QuarantineItem.alias_id)
            .where(
                QuarantineItem.user_id == user.id,
                QuarantineItem.released_at.is_(None),
                QuarantineItem.expires_at > datetime.now(UTC),
            )
            .order_by(QuarantineItem.created_at.desc())
        )
        return [(item, address) for item, address in (await self.db.execute(query)).all()]

    async def get_owned(self, user: User, item_id: uuid.UUID) -> QuarantineItem:
        """Load a pending item belonging to the user.

        Args:
            user: Owner.
            item_id: Item id.
        Returns:
            The item. Raises NotFound.
        """
        item = await self.db.get(QuarantineItem, item_id)
        if item is None or item.user_id != user.id or item.released_at is not None:
            raise NotFound("Quarantined message not found")
        return item

    async def _alias_of(self, item: QuarantineItem) -> Alias:
        """The alias a held message was sent to.

        Args:
            item: Quarantine row.
        Returns:
            The alias. Raises Conflict when it was forgotten.
        """
        alias = await self.db.get(Alias, item.alias_id) if item.alias_id else None
        if alias is None:
            raise Conflict("The alias for this message no longer exists")
        return alias

    async def request_release(self, user: User, item_id: uuid.UUID) -> None:
        """Check the release is possible and hand it to the worker (the API never sends mail).

        Args:
            user: Owner.
            item_id: Item id.
        Returns:
            None. Raises NotFound or Conflict.
        """
        await self._alias_of(await self.get_owned(user, item_id))
        task_dispatch.dispatch(RELEASE_TASK, str(item_id))

    async def release(self, item_id: uuid.UUID, forward: ReleaseForwarder) -> HandlerResult | None:
        """Decrypt a held message, deliver it through the forward path, then drop the copy.

        Args:
            item_id: Item id.
            forward: Forwards (envelope, raw) without the spam check.
        Returns:
            The forward result, or None if the item is gone or already released.
            Raises RetryableError (e.g. global cap), so the task retries.
        """
        item = await self.db.get(QuarantineItem, item_id)
        if item is None or item.released_at is not None:
            return None
        alias = await self._alias_of(item)
        try:
            raw = decrypt_bytes(await self.storage.get(item.r2_key))
        except R2ObjectMissing:
            return None
        env = InboundEnvelope(
            lease_id=f"release-{item.id}",
            attempts=0,
            r2_key=item.r2_key,  # also the forward dedup key, so a double release sends once
            mail_from=item.sender,
            rcpt_to=alias.address,
            raw_size=len(raw),
            received_at=item.created_at,
        )
        result = await forward(env, raw)
        # Keep the copy when nothing was delivered (e.g. alias inactive), so it can be retried.
        if result.outcome == Outcome.DELIVERED:
            item.released_at = datetime.now(UTC)
            await self.storage.delete(item.r2_key)
        return result

    async def delete(self, user: User, item_id: uuid.UUID) -> None:
        """Remove a held message and its row.

        Args:
            user: Owner.
            item_id: Item id.
        Returns:
            None. Raises NotFound.
        """
        item = await self.get_owned(user, item_id)
        await self.storage.delete(item.r2_key)
        await self.db.delete(item)


def subject_of(msg: EmailMessage) -> str | None:
    """Subject for the quarantine list (trimmed).

    Args:
        msg: Parsed message.
    Returns:
        The subject or None.
    """
    subject = msg.get("Subject")
    return str(subject)[:300] if subject is not None else None
