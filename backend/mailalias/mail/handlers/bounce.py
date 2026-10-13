"""BounceHandler: record DSNs that arrive at a reply token; they are never forwarded."""

# 1st party imports
import logging
from email.message import EmailMessage

# 3rd party imports
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.config import Settings
from mailalias.mail.addresses import split_address
from mailalias.mail.dsn import parse_dsn
from mailalias.mail.outbound import OutboundMailer
from mailalias.mail.types import HandlerResult, InboundEnvelope, MailKind, Outcome
from mailalias.models import Alias, FailureKind
from mailalias.services import mail_log
from mailalias.services.contacts import ContactService
from mailalias.services.failed_deliveries import FailedDeliveryService
from mailalias.services.system_mail import SystemMailService

logger = logging.getLogger(__name__)


class BounceHandler:
    """Token -> contact -> alias/user; DSN -> failed delivery (and recipient bounce count)."""

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        mailer: OutboundMailer,
        redis: Redis,
        system_mail: SystemMailService,
    ) -> None:
        """Build the handler (same collaborators as the other handlers).

        Args:
            db: Session (the handler commits).
            settings, mailer, redis: Unused beyond the shared handler signature.
            system_mail: For the "recipient disabled" notice.
        Returns:
            None.
        """
        self.db = db
        self.failed = FailedDeliveryService(db, system_mail)

    async def handle(self, env: InboundEnvelope, msg: EmailMessage) -> HandlerResult:
        """Record one DSN.

        Args:
            env: Envelope (rcpt_to is the token address).
            msg: Parsed DSN.
        Returns:
            BOUNCE_RECORDED (or DISCARDED for an unknown token / unparsable report).
        """
        contact = await ContactService(self.db).resolve_token(split_address(env.rcpt_to)[0])
        alias = await self.db.get(Alias, contact.alias_id) if contact else None
        info = parse_dsn(msg)
        if alias is None or info is None:
            reason = "unknown_token" if alias is None else "unparsable_dsn"
            return await self._finish(Outcome.DISCARDED, reason, env, alias)
        kind = (
            FailureKind.HARD
            if info.is_hard
            else FailureKind.DELAYED
            if info.action == "delayed"
            else FailureKind.SOFT
        )
        # If the failed address is one of the owner's recipients, it counts toward auto-disable.
        matches = (
            await self.failed.recipients_for(info.final_recipient, alias.user_id)
            if alias.user_id and info.final_recipient
            else []
        )
        detail = " - ".join(part for part in (info.status, info.diagnostic) if part) or None
        await self.failed.record(
            kind,
            user_id=alias.user_id,
            alias_id=alias.id,
            recipient=matches[0] if matches else None,
            detail=detail,
        )
        return await self._finish(Outcome.BOUNCE_RECORDED, kind.value, env, alias)

    async def _finish(
        self, outcome: Outcome, reason: str | None, env: InboundEnvelope, alias: Alias | None
    ) -> HandlerResult:
        """Write the mail log, commit, and build the result.

        Args:
            outcome, reason: What happened.
            env: Envelope (size).
            alias: Alias, if resolved.
        Returns:
            The HandlerResult.
        """
        await mail_log.record(
            self.db,
            kind=MailKind.BOUNCE,
            outcome=outcome,
            reason=reason,
            user_id=alias.user_id if alias else None,
            alias_id=alias.id if alias else None,
            size_bytes=env.raw_size,
        )
        await self.db.commit()
        return HandlerResult(outcome, reason)
