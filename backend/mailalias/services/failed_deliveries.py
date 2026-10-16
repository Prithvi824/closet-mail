"""Failed deliveries: record bounces/complaints and disable recipients that keep hard-bouncing."""

# 1st party imports
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

# 3rd party imports
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.mail.types import MailKind
from mailalias.models import (
    Alias,
    FailedDelivery,
    FailureKind,
    MailLog,
    Recipient,
    User,
    UserRole,
)
from mailalias.security.crypto import lookup_hash
from mailalias.services.system_mail import SystemMailService

logger = logging.getLogger(__name__)

HARD_BOUNCE_LIMIT = 3
HARD_BOUNCE_WINDOW = timedelta(days=7)
EVENT_KINDS = {
    "email.complained": FailureKind.COMPLAINT,
    "email.delivery_delayed": FailureKind.DELAYED,
    "email.suppressed": FailureKind.SUPPRESSED,
}
DETAIL_MAX_CHARS = 1000
LIST_LIMIT = 200


def _event_kind(event_type: str, data: dict[str, Any]) -> FailureKind | None:
    """Map a Resend event to a failure kind.

    Args:
        event_type: e.g. "email.bounced".
        data: Event data (bounce.type decides hard or soft).
    Returns:
        The kind, or None for events we do not record.
    """
    if event_type == "email.bounced":
        bounce_type = str((data.get("bounce") or {}).get("type", "")).lower()
        return FailureKind.HARD if bounce_type == "permanent" else FailureKind.SOFT
    return EVENT_KINDS.get(event_type)


def _event_detail(data: dict[str, Any]) -> str | None:
    """Human-readable detail from an event (bounce message and subtype).

    Args:
        data: Event data.
    Returns:
        Detail text or None.
    """
    bounce = data.get("bounce") or {}
    parts = [str(bounce.get(key)) for key in ("type", "subType", "message") if bounce.get(key)]
    return " - ".join(parts) or None


class FailedDeliveryService:
    """Stores delivery problems and applies the hard-bounce auto-disable rule."""

    def __init__(self, db: AsyncSession, system_mail: SystemMailService) -> None:
        """Build the service.

        Args:
            db: Session (the caller commits).
            system_mail: For the "recipient disabled" notice.
        Returns:
            None.
        """
        self.db = db
        self.system_mail = system_mail

    async def log_for_provider_id(self, provider_id: str) -> MailLog | None:
        """The mail log row of a message we sent, by the relay's message id.

        Args:
            provider_id: Resend email id.
        Returns:
            The row, or None.
        """
        query = select(MailLog).where(MailLog.provider_id == provider_id).limit(1)
        return await self.db.scalar(query)

    async def recipients_for(self, address: str, user_id: uuid.UUID | None) -> list[Recipient]:
        """Recipients with this address (only the given user's when known).

        Args:
            address: Bounced address.
            user_id: Owner, if the message could be traced.
        Returns:
            Matching recipients (several users may share an address).
        """
        query = select(Recipient).where(Recipient.email_hash == lookup_hash(address))
        if user_id is not None:
            query = query.where(Recipient.user_id == user_id)
        return list(await self.db.scalars(query))

    async def record(
        self,
        kind: FailureKind,
        *,
        user_id: uuid.UUID | None,
        alias_id: uuid.UUID | None = None,
        recipient: Recipient | None = None,
        provider_event_id: str | None = None,
        detail: str | None = None,
    ) -> FailedDelivery | None:
        """Store one failure; a hard bounce also counts toward disabling the recipient.

        Args:
            kind: Failure type.
            user_id, alias_id, recipient: What it belongs to, when known.
            provider_event_id: Webhook event id (duplicates are ignored).
            detail: Provider/DSN text (stored encrypted, trimmed).
        Returns:
            The new row, or None for a duplicate event.
        """
        entry = FailedDelivery(
            user_id=recipient.user_id if recipient else user_id,
            recipient_id=recipient.id if recipient else None,
            alias_id=alias_id,
            kind=kind,
            provider_event_id=provider_event_id,
            detail=detail[:DETAIL_MAX_CHARS] if detail else None,
        )
        try:
            async with self.db.begin_nested():
                self.db.add(entry)
        except IntegrityError:
            return None
        if kind == FailureKind.HARD and recipient is not None:
            await self._count_hard_bounce(recipient)
        return entry

    async def record_email_event(self, event_id: str, event: dict[str, Any]) -> int:
        """Record a verified Resend webhook event (bounce, complaint, delay, suppression).

        Args:
            event_id: svix-id header (de-duplicates retries).
            event: Parsed payload: {"type", "data": {"email_id", "to", "bounce": {...}}}.
        Returns:
            Number of failure rows written (0 for duplicates or ignored event types).
        """
        data = event.get("data") or {}
        kind = _event_kind(str(event.get("type", "")), data)
        recipients_to = data.get("to") or []
        if kind is None or not recipients_to:
            return 0
        log = await self.log_for_provider_id(str(data.get("email_id", "")))
        user_id, alias_id = (log.user_id, log.alias_id) if log else (None, None)
        detail = _event_detail(data)
        # A bounced reply concerns the correspondent, never the owner's recipients.
        matches = (
            []
            if log and log.kind == MailKind.REPLY
            else await self.recipients_for(str(recipients_to[0]), user_id)
        )
        if not matches:
            entry = await self.record(
                kind, user_id=user_id, alias_id=alias_id, provider_event_id=event_id, detail=detail
            )
            return int(entry is not None)
        written = 0
        for index, recipient in enumerate(matches):
            # Several users can share an address; only the first row carries the event id.
            event_key = event_id if index == 0 else f"{event_id}:{recipient.id}"
            entry = await self.record(
                kind,
                user_id=user_id,
                alias_id=alias_id,
                recipient=recipient,
                provider_event_id=event_key,
                detail=detail,
            )
            written += entry is not None
        return written

    async def _count_hard_bounce(self, recipient: Recipient) -> None:
        """Recount recent hard bounces; disable the recipient and tell the user on the limit.

        Args:
            recipient: Recipient that hard-bounced (its new failure row is already flushed).
        Returns:
            None.
        """
        # Bounces arrive by webhook after the send was accepted, so a successful send can't reset
        # a streak. Counting hard bounces inside a window keeps old one-offs from adding up.
        since = datetime.now(UTC) - HARD_BOUNCE_WINDOW
        count = await self.db.scalar(
            select(func.count())
            .select_from(FailedDelivery)
            .where(
                FailedDelivery.recipient_id == recipient.id,
                FailedDelivery.kind == FailureKind.HARD,
                FailedDelivery.created_at >= since,
            )
        )
        await self.db.execute(
            update(Recipient)
            .where(Recipient.id == recipient.id)
            .values(consecutive_hard_bounces=count or 0)
        )
        await self.db.refresh(recipient)
        if count is None or count < HARD_BOUNCE_LIMIT or recipient.disabled_at is not None:
            return
        recipient.disabled_at = datetime.now(UTC)
        await self.db.flush()
        logger.warning(
            "recipient disabled after hard bounces", extra={"recipient_id": str(recipient.id)}
        )
        await self._notify_disabled(recipient)

    async def _notify_disabled(self, recipient: Recipient) -> None:
        """Tell the user (other usable recipients, else the admins) that forwarding stopped.

        Args:
            recipient: The recipient just disabled (never mailed itself).
        Returns:
            None.
        """
        others = await self.db.scalars(
            select(Recipient).where(
                Recipient.user_id == recipient.user_id, Recipient.id != recipient.id
            )
        )
        targets = [r.email for r in others if r.is_usable]
        if not targets:
            admins = await self.db.scalars(select(User).where(User.role == UserRole.ADMIN))
            targets = [admin.email for admin in admins if admin.disabled_at is None]
        for address in dict.fromkeys(targets):
            await self.system_mail.send(
                "notice",
                address,
                subject="A forwarding address was disabled",
                body=(
                    f"Mail to {recipient.email} bounced {HARD_BOUNCE_LIMIT} times in a row, so "
                    "forwarding to it has been turned off. Fix the mailbox, then re-enable it "
                    "from the Recipients page."
                ),
            )

    async def list_for_user(
        self, user: User
    ) -> list[tuple[FailedDelivery, str | None, str | None]]:
        """The user's recent failures with the recipient and alias addresses, newest first.

        Args:
            user: Owner.
        Returns:
            (failure, recipient address, alias address) triples.
        """
        query = (
            select(FailedDelivery, Recipient, Alias.address)
            .outerjoin(Recipient, Recipient.id == FailedDelivery.recipient_id)
            .outerjoin(Alias, Alias.id == FailedDelivery.alias_id)
            .where(FailedDelivery.user_id == user.id)
            .order_by(FailedDelivery.created_at.desc())
            .limit(LIST_LIMIT)
        )
        rows = (await self.db.execute(query)).all()
        return [(row[0], row[1].email if row[1] else None, row[2]) for row in rows]
