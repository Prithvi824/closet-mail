"""ReplyHandler: send the owner's reply (to a contact's token) out from the alias."""

# 1st party imports
import logging
from email.message import EmailMessage
from email.utils import getaddresses

# 3rd party imports
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.config import Settings
from mailalias.mail import auth_results
from mailalias.mail.addresses import normalize, split_address
from mailalias.mail.outbound import OutboundMailer, PermanentSendError
from mailalias.mail.transform.context import ReplyContext
from mailalias.mail.transform.reply import build_reply
from mailalias.mail.types import HandlerResult, InboundEnvelope, MailKind, Outcome, RetryableError
from mailalias.models import Alias, AliasState, Contact, Recipient, User
from mailalias.security.crypto import lookup_hash
from mailalias.services import mail_log
from mailalias.services.contacts import ContactService
from mailalias.services.notices import notify_owner
from mailalias.services.quota import QuotaService, cap_retry_delay
from mailalias.services.system_mail import SystemMailService

logger = logging.getLogger(__name__)

NOTICE_TTL_SECONDS = 3600
DONE_TTL_SECONDS = 4 * 86_400
REJECTION_TEXT = {
    "alias_deleted": "the alias has been deleted",
    "reply_disabled": "replies are turned off for this alias",
    "unauthorized_sender": "it was not sent from one of your verified recipient addresses",
    "dmarc_fail": "the sending address failed DMARC authentication",
    "quota": "your daily reply limit was reached",
}


class ReplyHandler:
    """Coordinates one reply: token -> contact -> alias -> owner checks -> transform -> send."""

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        mailer: OutboundMailer,
        redis: Redis,
        system_mail: SystemMailService,
    ) -> None:
        """Build the handler for one message.

        Args:
            db: Session for this message (the handler commits).
            settings: Settings.
            mailer: Outbound mailer.
            redis: Redis (quotas, dedup, notice throttling).
            system_mail: Owner notices.
        Returns:
            None.
        """
        self.db = db
        self.settings = settings
        self.mailer = mailer
        self.redis = redis
        self.system_mail = system_mail
        self.quota = QuotaService(redis, settings)
        self.contacts = ContactService(db)

    async def _finish(
        self,
        outcome: Outcome,
        reason: str | None,
        env: InboundEnvelope,
        alias: Alias | None = None,
        contact: Contact | None = None,
        provider_id: str | None = None,
    ) -> HandlerResult:
        """Write the mail log, commit, and build the result.

        Args:
            outcome, reason: What happened.
            env: Envelope (size).
            alias, contact: Resolved objects, if any.
            provider_id: Provider id of the sent reply.
        Returns:
            The HandlerResult.
        """
        await mail_log.record(
            self.db,
            kind=MailKind.REPLY,
            outcome=outcome,
            reason=reason,
            user_id=alias.user_id if alias else None,
            alias_id=alias.id if alias else None,
            contact_id=contact.id if contact else None,
            size_bytes=env.raw_size,
            provider_id=provider_id,
        )
        await self.db.commit()
        return HandlerResult(outcome, reason)

    async def _reject(
        self, reason: str, env: InboundEnvelope, alias: Alias, owner: User, contact: Contact
    ) -> HandlerResult:
        """Drop the reply and tell the owner (at most once an hour per alias and reason).

        Args:
            reason: Reason code (key of REJECTION_TEXT).
            env: Envelope.
            alias, owner, contact: Resolved objects.
        Returns:
            REJECTED_REPLY (DISCARDED for quota).
        """
        await notify_owner(
            self.redis,
            self.system_mail,
            owner,
            throttle_key=f"reply:{alias.id}:{reason}",
            ttl_seconds=NOTICE_TTL_SECONDS,
            subject=f"Reply from {alias.address} was not sent",
            body=f"A reply sent from {alias.address} was not delivered because "
            f"{REJECTION_TEXT[reason]}.",
        )
        outcome = Outcome.DISCARDED if reason == "quota" else Outcome.REJECTED_REPLY
        return await self._finish(outcome, reason, env, alias, contact)

    async def _owner_addresses(self, owner: User) -> tuple[set[str], list[str]]:
        """Hashes of usable recipients (authorised senders) and every owner address.

        Args:
            owner: Alias owner.
        Returns:
            (allowed sender hashes, all owner addresses to scrub).
        """
        recipients = list(
            await self.db.scalars(select(Recipient).where(Recipient.user_id == owner.id))
        )
        allowed = {r.email_hash for r in recipients if r.is_usable}
        addresses = {normalize(r.email) for r in recipients} | {normalize(owner.email)}
        return allowed, sorted(addresses)

    def _is_authorised(self, env: InboundEnvelope, msg: EmailMessage, allowed: set[str]) -> bool:
        """Both the envelope sender and every header From must be the owner's recipients.

        Args:
            env: Envelope.
            msg: Parsed message.
            allowed: Allowed sender hashes.
        Returns:
            True if authorised.
        """
        header_from = [addr for _, addr in getaddresses([str(msg.get("From", ""))]) if addr]
        if not env.mail_from or len(header_from) != 1:
            return False
        return {lookup_hash(env.mail_from), lookup_hash(header_from[0])} <= allowed

    async def _map_recipients(
        self, msg: EmailMessage, alias: Alias
    ) -> tuple[dict[str, tuple[tuple[str, str], ...]], dict[str, str], bool]:
        """Translate token addresses in To/Cc to real ones on the same alias.

        Args:
            msg: Parsed message.
            alias: The alias being replied from.
        Returns:
            ({"To": pairs, "Cc": pairs}, token address -> real address, whether any
            address had to be removed).
        """
        mapped: dict[str, tuple[tuple[str, str], ...]] = {}
        tokens: dict[str, str] = {}
        removed = False
        for header in ("To", "Cc"):
            pairs: list[tuple[str, str]] = []
            for _, address in getaddresses([str(value) for value in msg.get_all(header, [])]):
                address = normalize(address)
                if not address or address == alias.address:
                    continue
                local, domain = split_address(address) if "@" in address else ("", "")
                contact = (
                    await self.contacts.resolve_token(local)
                    if domain == self.settings.reply_domain
                    else None
                )
                if contact is None or contact.alias_id != alias.id:
                    removed = True
                    continue
                real = self.contacts.real_address(contact)
                tokens[address] = real
                pairs.append((contact.sender_name or "", real))
            mapped[header] = tuple(pairs)
        return mapped, tokens, removed

    async def handle(self, env: InboundEnvelope, msg: EmailMessage) -> HandlerResult:
        """Validate and send one reply to the contact behind the envelope token.

        Args:
            env: Envelope (rcpt_to is the token address).
            msg: Parsed message.
        Returns:
            HandlerResult. Raises RetryableError for infrastructure problems or the global cap.
        """
        contact = await self.contacts.resolve_token(split_address(env.rcpt_to)[0])
        alias = await self.db.get(Alias, contact.alias_id) if contact else None
        owner = await self.db.get(User, alias.user_id) if alias and alias.user_id else None
        if contact is None or alias is None or owner is None or owner.disabled_at is not None:
            return await self._finish(Outcome.REJECTED_REPLY, "unknown_token", env, alias, contact)
        if alias.state in (AliasState.DELETED, AliasState.FORGOTTEN):
            return await self._reject("alias_deleted", env, alias, owner, contact)
        if not alias.reply_enabled:
            return await self._reject("reply_disabled", env, alias, owner, contact)
        allowed, owner_addresses = await self._owner_addresses(owner)
        if not self._is_authorised(env, msg, allowed):
            return await self._reject("unauthorized_sender", env, alias, owner, contact)
        if auth_results.parse(msg).dmarc != "pass":
            return await self._reject("dmarc_fail", env, alias, owner, contact)

        mapped, tokens, removed = await self._map_recipients(msg, alias)
        real_address = self.contacts.real_address(contact)
        if not mapped["To"] and not mapped["Cc"]:
            mapped["To"] = ((contact.sender_name or "", real_address),)
        if removed:
            await notify_owner(
                self.redis,
                self.system_mail,
                owner,
                throttle_key=f"reply:{alias.id}:filtered",
                ttl_seconds=NOTICE_TTL_SECONDS,
                subject=f"Some recipients were removed from a reply from {alias.address}",
                body="Replies through an alias can only reach that alias's contacts. Other "
                "addresses in To/Cc were removed and did not receive your message.",
            )
        return await self._send(env, msg, alias, owner, contact, mapped, tokens, owner_addresses)

    async def _send(
        self,
        env: InboundEnvelope,
        msg: EmailMessage,
        alias: Alias,
        owner: User,
        contact: Contact,
        mapped: dict[str, tuple[tuple[str, str], ...]],
        tokens: dict[str, str],
        owner_addresses: list[str],
    ) -> HandlerResult:
        """Check quotas, build the reply and send it to this envelope's contact only.

        Args:
            env, msg: Inbound message.
            alias, owner, contact: Resolved objects.
            mapped, tokens: Header recipients and token rewrites.
            owner_addresses: Addresses to scrub.
        Returns:
            HandlerResult.
        """
        done_key = f"reply:done:{env.r2_key}"
        if await self.redis.exists(done_key):
            return await self._finish(Outcome.DELIVERED, "redelivered", env, alias, contact)
        if not await self.quota.global_send_allowed():
            raise RetryableError("global send cap reached", cap_retry_delay())
        if not await self.quota.check_and_consume(owner.id, "reply", limits=owner.limits):
            await self.quota.refund_global()
            return await self._reject("quota", env, alias, owner, contact)

        base = self.settings.app_base_url.rstrip("/")
        reply = build_reply(
            msg,
            ReplyContext(
                alias_address=alias.address,
                to=mapped["To"],
                cc=mapped["Cc"],
                owner_addresses=tuple(owner_addresses),
                token_addresses=tokens,
                action_url_prefix=f"{base}/a/",
            ),
        )
        try:
            provider_id = await self.mailer.send(
                reply, alias.address, [self.contacts.real_address(contact)]
            )
        except RetryableError:
            await self.quota.refund_global()
            await self.quota.refund_user(owner.id, "reply")
            raise
        except PermanentSendError:
            logger.warning("reply rejected", extra={"contact_id": str(contact.id)})
            await self.quota.refund_global()
            await self.quota.refund_user(owner.id, "reply")
            return await self._finish(Outcome.DISCARDED, "send_failed", env, alias, contact)
        await self.redis.set(done_key, "1", ex=DONE_TTL_SECONDS)
        return await self._finish(Outcome.DELIVERED, None, env, alias, contact, provider_id)
