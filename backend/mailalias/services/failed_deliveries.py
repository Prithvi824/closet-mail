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
    DeliveryLog,
    DeliveryStatus,
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
# Resend event -> status of the matching send (delivery_log row).
EVENT_STATUSES = {
    "email.delivered": DeliveryStatus.DELIVERED,
    "email.bounced": DeliveryStatus.BOUNCED,
    "email.complained": DeliveryStatus.COMPLAINED,
    "email.delivery_delayed": DeliveryStatus.DELAYED,
    "email.suppressed": DeliveryStatus.BOUNCED,
}
# A late "delayed" event must not hide an outcome that is already known.
FINAL_STATUSES = frozenset(
    {DeliveryStatus.DELIVERED, DeliveryStatus.BOUNCED, DeliveryStatus.COMPLAINED}
)
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

    async def recipients_for(self, address: str, user_id: uuid.UUID) -> list[Recipient]:
        """One subdomain's recipients with this address (never matched across subdomains).

        Args:
            address: Bounced address.
            user_id: Owner the message was traced to.
        Returns:
            Matching recipients of that owner.
        """
        query = select(Recipient).where(
            Recipient.email_hash == lookup_hash(address), Recipient.user_id == user_id
        )
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
        """Apply a verified Resend event to its send, recording failures against that inbox.

        Args:
            event_id: svix-id header (de-duplicates retries).
            event: Parsed payload: {"type", "data": {"email_id", "to", "bounce": {...}}}.
        Returns:
            Number of failure rows written (0 for duplicates, deliveries or ignored types).
        """
        event_type = str(event.get("type", ""))
        data = event.get("data") or {}
        kind = _event_kind(event_type, data)
        email_id = str(data.get("email_id", ""))
        delivery = await self._delivery_for(email_id) if email_id else None
        if delivery is not None:
            self._apply_status(delivery, EVENT_STATUSES.get(event_type))
            if kind is None:
                await self.db.flush()
                return 0
            return await self._record_for_delivery(delivery, kind, event_id, _event_detail(data))
        recipients_to = data.get("to") or []
        if kind is None or not recipients_to:
            return 0
        return await self._record_untraced(
            email_id, kind, str(recipients_to[0]), event_id, _event_detail(data)
        )

    async def _delivery_for(self, provider_id: str) -> DeliveryLog | None:
        """The send with this provider id, locked so concurrent events apply in turn.

        Args:
            provider_id: Resend email id.
        Returns:
            The delivery row, or None (older mail, or not ours).
        """
        query = select(DeliveryLog).where(DeliveryLog.provider_id == provider_id).with_for_update()
        return await self.db.scalar(query)

    @staticmethod
    def _apply_status(delivery: DeliveryLog, status: DeliveryStatus | None) -> None:
        """Move a send to the event's status, never back from a final one to "delayed".

        Args:
            delivery: The send.
            status: New status (None for events that carry none).
        Returns:
            None.
        """
        if status is None:
            return
        if status == DeliveryStatus.DELAYED and delivery.status in FINAL_STATUSES:
            return
        delivery.status = status
        delivery.status_at = datetime.now(UTC)

    async def _record_for_delivery(
        self, delivery: DeliveryLog, kind: FailureKind, event_id: str, detail: str | None
    ) -> int:
        """Record a failure of one traced send; only a forward's inbox counts toward disabling.

        Args:
            delivery: The send the event is about.
            kind, event_id, detail: Failure type, svix-id and provider text.
        Returns:
            1 when a row was written, else 0.
        """
        log = await self.db.get(MailLog, delivery.mail_log_id)
        alias_id = log.alias_id if log else None
        recipient = (
            await self.db.get(Recipient, delivery.recipient_id)
            if delivery.recipient_id and log is not None and log.kind == MailKind.FORWARD
            else None
        )
        entry = await self.record(
            kind,
            user_id=delivery.user_id,
            alias_id=alias_id,
            recipient=recipient,
            provider_event_id=event_id,
            detail=detail,
        )
        return int(entry is not None)

    async def _record_untraced(
        self, email_id: str, kind: FailureKind, address: str, event_id: str, detail: str | None
    ) -> int:
        """Fallback for sends logged before delivery rows existed: match within that owner only.

        Args:
            email_id: Resend email id (matched against the legacy mail_log.provider_id).
            kind, address, event_id, detail: Failure type, failed address, svix-id, text.
        Returns:
            Number of failure rows written.
        """
        log = await self.log_for_provider_id(email_id) if email_id else None
        user_id, alias_id = (log.user_id, log.alias_id) if log else (None, None)
        # A bounced reply concerns the correspondent, never the owner's recipients.
        matches = (
            await self.recipients_for(address, user_id)
            if log is not None and user_id is not None and log.kind == MailKind.FORWARD
            else []
        )
        if not matches:
            entry = await self.record(
                kind, user_id=user_id, alias_id=alias_id, provider_event_id=event_id, detail=detail
            )
            return int(entry is not None)
        written = 0
        for index, recipient in enumerate(matches):
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
