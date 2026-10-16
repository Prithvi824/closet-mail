"""ForwardHandler: deliver mail sent to an alias to the owner's recipients via the reply token."""

# 1st party imports
import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import getaddresses

# 3rd party imports
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# local imports
from mailalias.api.errors import Conflict, DomainError
from mailalias.config import Settings
from mailalias.integrations.r2 import ObjectStore
from mailalias.integrations.rspamd import SpamChecker, SpamCheckUnavailable
from mailalias.mail import auth_results
from mailalias.mail.addresses import is_service_domain, normalize, split_address
from mailalias.mail.outbound import OutboundMailer, PermanentSendError
from mailalias.mail.transform.context import BannerSettings, TransformContext
from mailalias.mail.transform.forward import build_forward
from mailalias.mail.transform.headers import ALIAS_HEADER, NOTICE_HEADER
from mailalias.mail.types import HandlerResult, InboundEnvelope, MailKind, Outcome, RetryableError
from mailalias.models import Alias, AliasState, Contact, Recipient, User
from mailalias.security.signing import sign_action
from mailalias.services import mail_log
from mailalias.services.aliases import AliasService
from mailalias.services.blocklist import BlocklistService
from mailalias.services.contacts import ContactService
from mailalias.services.notices import notify_owner
from mailalias.services.quarantine import QuarantineService, subject_of
from mailalias.services.quota import QuotaService, cap_retry_delay
from mailalias.services.system_mail import SystemMailService

logger = logging.getLogger(__name__)

DONE_TTL_SECONDS = 4 * 86_400  # longer than the R2 inbox lifecycle (3 days)
QUOTA_NOTICE_TTL_SECONDS = 86_400


def sender_of(env: InboundEnvelope, msg: EmailMessage) -> tuple[str, str | None]:
    """The correspondent: header From (what the owner sees), else the envelope sender.

    Args:
        env: Envelope.
        msg: Parsed message.
    Returns:
        (address, display name or None); address is "" when neither exists.
    """
    for name, address in getaddresses([str(msg.get("From", ""))]):
        if "@" in address:
            return normalize(address), name.strip() or None
    return normalize(env.mail_from), None


def sender_display(address: str, name: str | None) -> str:
    """Display name for the token From, e.g. "Alice (alice at example.com)".

    Args:
        address: Sender address.
        name: Sender display name.
    Returns:
        The display string.
    """
    readable = address.replace("@", " at ")
    return f"{name} ({readable})" if name else readable


@dataclass(frozen=True)
class Delivery:
    """What _deliver needs once routing and screening are done."""

    alias: Alias
    owner: User
    contact: Contact
    recipients: list[Recipient]
    address: str  # sender address (for the display string)
    name: str | None
    spam_score: float | None
    spam_unchecked: bool  # Rspamd was unavailable: add a notice header


class ForwardHandler:
    """Coordinates one forward: alias -> recipients -> contact -> quotas -> transform -> send."""

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        mailer: OutboundMailer,
        redis: Redis,
        system_mail: SystemMailService,
        *,
        spam: SpamChecker | None = None,
        storage: ObjectStore | None = None,
    ) -> None:
        """Build the handler for one message.

        Args:
            db: Session for this message (the handler commits).
            settings, mailer, redis: Settings, outbound mailer, Redis (quotas, dedup, throttling).
            system_mail: For owner notices (quota reached).
            spam: Spam scorer; None means unavailable (mail is delivered with a notice).
            storage: Object store for quarantined messages (required when spam is set).
        Returns:
            None.
        """
        self.db = db
        self.settings = settings
        self.mailer = mailer
        self.redis = redis
        self.system_mail = system_mail
        self.spam = spam
        self.storage = storage
        self.quota = QuotaService(redis, settings)

    async def _log(
        self,
        outcome: Outcome,
        reason: str | None,
        env: InboundEnvelope,
        alias: Alias | None = None,
        contact: Contact | None = None,
        provider_id: str | None = None,
        spam_score: float | None = None,
    ) -> HandlerResult:
        """Write the mail log, commit, and build the result.

        Args:
            outcome, reason: What happened.
            env: Envelope (size).
            alias, contact: Resolved objects, if any.
            provider_id, spam_score: Provider id of the first delivery; Rspamd score.
        Returns:
            The HandlerResult.
        """
        await mail_log.record(
            self.db,
            kind=MailKind.FORWARD,
            outcome=outcome,
            reason=reason,
            user_id=alias.user_id if alias else None,
            alias_id=alias.id if alias else None,
            contact_id=contact.id if contact else None,
            size_bytes=env.raw_size,
            provider_id=provider_id,
            spam_score=spam_score,
        )
        await self.db.commit()
        return HandlerResult(outcome, reason)

    async def _spam_score(
        self, env: InboundEnvelope, msg: EmailMessage, raw: bytes
    ) -> float | None:
        """Score the message with Rspamd, passing the client IP/HELO Cloudflare recorded.

        Args:
            env: Envelope.
            msg: Parsed message.
            raw: Raw bytes.
        Returns:
            The score, or None when the scanner is unavailable.
        """
        if self.spam is None:
            return None
        ip, helo = auth_results.client_info(msg)
        try:
            verdict = await self.spam.check(raw, env.mail_from, env.rcpt_to, ip, helo)
        except SpamCheckUnavailable as exc:
            logger.warning("spam check unavailable", extra={"error": str(exc)})
            return None
        return verdict.score

    async def _screen(
        self,
        env: InboundEnvelope,
        msg: EmailMessage,
        raw: bytes,
        alias: Alias,
        contact: Contact,
        score: float | None,
    ) -> HandlerResult | None:
        """Discard or quarantine spam (and DMARC failures of p=reject domains).

        Args:
            env, msg, raw: The inbound message.
            alias, contact: Resolved objects.
            score: Rspamd score, or None if unavailable.
        Returns:
            A final result when the message was discarded or held, else None (deliver).
        """
        if score is not None and score >= self.settings.spam_discard_score:
            return await self._log(Outcome.DISCARDED, "spam", env, alias, contact, None, score)
        auth = auth_results.parse(msg)
        dmarc_reject = auth.dmarc == "fail" and auth.dmarc_policy == "reject"
        spam = score is not None and score >= self.settings.spam_quarantine_score
        if not (spam or dmarc_reject):
            return None
        assert self.storage is not None, "quarantine needs an object store"
        await QuarantineService(self.db, self.settings, self.storage).hold(
            raw=raw,
            alias=alias,
            contact_id=contact.id,
            sender=ContactService(self.db).real_address(contact),
            subject=subject_of(msg),
            score=score if score is not None else 0.0,
        )
        reason = "spam" if spam else "dmarc_reject"
        return await self._log(Outcome.QUARANTINED, reason, env, alias, contact, None, score)

    async def _resolve_alias(self, address: str) -> Alias | None:
        """Load the alias, auto-creating it on a personal subdomain with catch-all on.

        Args:
            address: Normalised recipient address.
        Returns:
            The alias with recipients loaded, or None.
        """
        query = (
            select(Alias).options(selectinload(Alias.recipients)).where(Alias.address == address)
        )
        alias = await self.db.scalar(query)
        if alias is not None:
            return alias
        local, domain = split_address(address)
        username = domain.removesuffix("." + self.settings.alias_domain)
        if username == domain:
            return None
        owner = await self.db.scalar(select(User).where(User.username == username))
        if owner is None or not owner.subdomain_catchall or owner.disabled_at is not None:
            return None
        try:
            await AliasService(self.db, self.settings, self.redis).create(
                owner, local_part=local, subdomain=True
            )
        except Conflict:
            # Another message for the same new address created it first; load that one below.
            pass
        except DomainError as exc:
            logger.info("catch-all alias not created", extra={"code": exc.code})
            return None
        await self.db.commit()
        return await self.db.scalar(query.execution_options(populate_existing=True))

    async def _recipients(self, alias: Alias, owner: User) -> list[Recipient]:
        """Usable recipients of the alias, falling back to the owner's default.

        Args:
            alias: Alias with recipients loaded.
            owner: Alias owner.
        Returns:
            Recipients (never on a service domain).
        """
        recipients = [r for r in alias.recipients if r.is_usable]
        if not recipients and owner.default_recipient_id:
            default = await self.db.get(Recipient, owner.default_recipient_id)
            recipients = [default] if default is not None and default.is_usable else []
        return [
            r
            for r in recipients
            if not is_service_domain(split_address(r.email)[1], self.settings.alias_domain)
        ]

    def _context(
        self, alias: Alias, contact: Contact, owner: User, recipient: Recipient, display: str
    ) -> TransformContext:
        """Per-recipient transform context with signed one-click action links.

        Args:
            alias: Alias.
            contact: Contact.
            owner: Alias owner.
            recipient: Destination (PGP settings).
            display: Sender display string.
        Returns:
            The context.
        """
        base = self.settings.app_base_url.rstrip("/")
        block = sign_action({"a": "block_contact", "id": str(contact.id), "uid": str(owner.id)})
        disable = sign_action({"a": "disable_alias", "id": str(alias.id), "uid": str(owner.id)})
        return TransformContext(
            alias_address=alias.address,
            contact_token_address=f"{contact.token}@{self.settings.reply_domain}",
            sender_display=display,
            banner=BannerSettings(
                position=owner.banner_position.value,
                block_sender_url=f"{base}/a/{block}",
                disable_alias_url=f"{base}/a/{disable}",
            ),
            strip_trackers=owner.strip_trackers,
            pgp_public_key=recipient.pgp_public_key,
            pgp_protect_subject=recipient.pgp_protect_subject,
        )

    async def _notify_quota(self, owner: User) -> None:
        """Tell the owner (at most once a day) that forwards are being dropped.

        Args:
            owner: Alias owner.
        Returns:
            None.
        """
        await notify_owner(
            self.redis,
            self.system_mail,
            owner,
            throttle_key=f"quota:{owner.id}:{datetime.now(UTC):%Y%m%d}",
            ttl_seconds=QUOTA_NOTICE_TTL_SECONDS,
            subject="Forwarding limit reached",
            body=(
                "Your hourly forwarding limit was reached, so some messages were not "
                "forwarded. Forwarding resumes automatically next hour."
            ),
        )

    async def handle(
        self,
        env: InboundEnvelope,
        msg: EmailMessage,
        raw: bytes | None = None,
        *,
        skip_spam: bool = False,
    ) -> HandlerResult:
        """Forward one message to the alias owner's recipients.

        Args:
            env, msg: Envelope and parsed inbound message.
            raw: Raw bytes (re-serialised from msg when absent).
            skip_spam: Skip the spam screen (releasing from quarantine).
        Returns:
            HandlerResult. Raises RetryableError for infrastructure problems or the global cap.
        """
        address, name = sender_of(env, msg)
        alias = await self._resolve_alias(normalize(env.rcpt_to))
        if alias is None or alias.user_id is None:
            return await self._log(Outcome.DISCARDED, "unknown_alias", env, alias)
        if alias.state != AliasState.ACTIVE:
            reason = "alias_inactive" if alias.state == AliasState.INACTIVE else "alias_deleted"
            return await self._log(Outcome.DISCARDED, reason, env, alias)
        owner = await self.db.get(User, alias.user_id)
        if owner is None or owner.disabled_at is not None:
            return await self._log(Outcome.DISCARDED, "user_disabled", env, alias)
        # Our own forwards coming back (e.g. a recipient forwarding to an alias) would loop.
        if msg.get(ALIAS_HEADER) or (
            address and is_service_domain(split_address(address)[1], self.settings.reply_domain)
        ):
            return await self._log(Outcome.DISCARDED, "loop", env, alias)
        if not address:
            return await self._log(Outcome.DISCARDED, "no_sender", env, alias)
        recipients = await self._recipients(alias, owner)
        if not recipients:
            return await self._log(Outcome.DISCARDED, "no_recipient", env, alias)

        if await BlocklistService(self.db).is_blocked(owner.id, address):
            return await self._log(Outcome.BLOCKED, "blocklist", env, alias)
        contact = await ContactService(self.db).get_or_create(alias, address, name)
        # Commit now so the reply token in the delivered mail exists even if a later step fails.
        await self.db.commit()
        if contact.blocked:
            return await self._log(Outcome.BLOCKED, "contact_blocked", env, alias, contact)
        score: float | None = None
        unchecked = False
        if not skip_spam:
            raw = raw if raw is not None else msg.as_bytes()
            score = await self._spam_score(env, msg, raw)
            unchecked = score is None
            held = await self._screen(env, msg, raw, alias, contact, score)
            if held is not None:
                return held
        delivery = Delivery(alias, owner, contact, recipients, address, name, score, unchecked)
        return await self._deliver(env, msg, delivery)

    async def _deliver(
        self, env: InboundEnvelope, msg: EmailMessage, delivery: Delivery
    ) -> HandlerResult:
        """Check quotas, then build and send one copy per pending recipient.

        Args:
            env, msg: The inbound message.
            delivery: Resolved routing objects, sender identity and spam result.
        Returns:
            HandlerResult (DELIVERED, or DISCARDED for quota / send failures).
        """
        alias, owner, contact = delivery.alias, delivery.owner, delivery.contact
        recipients, score = delivery.recipients, delivery.spam_score
        done_key = f"fwd:done:{env.r2_key}"
        done = set(await self.redis.smembers(done_key))
        pending = [r for r in recipients if str(r.id) not in done]
        cost = len(pending)
        if cost and not await self.quota.global_send_allowed(cost):
            raise RetryableError("global send cap reached", cap_retry_delay())
        if cost and not await self.quota.check_and_consume(
            owner.id, "forward", cost, limits=owner.limits
        ):
            await self.quota.refund_global(cost)
            await self._notify_quota(owner)
            return await self._log(Outcome.DISCARDED, "quota", env, alias, contact, None, score)

        display = sender_display(delivery.address, delivery.name)
        provider_id: str | None = None
        delivered = len(recipients) - cost
        for index, recipient in enumerate(pending):
            context = self._context(alias, contact, owner, recipient, display)
            try:
                # PGP runs a gpg subprocess per message; keep it off the event loop.
                if context.pgp_public_key:
                    message = await asyncio.to_thread(build_forward, msg, context)
                else:
                    message = build_forward(msg, context)
            except Exception:
                # A broken key or unparseable part fails the same way on every retry, so skip this
                # recipient (never fall back to plaintext) and keep going with the others.
                logger.exception("forward build failed", extra={"recipient_id": str(recipient.id)})
                await self.quota.refund_global(1)
                await self.quota.refund_user(owner.id, "forward", 1)
                continue
            if delivery.spam_unchecked:
                message[NOTICE_HEADER] = "spam-check-unavailable"
            try:
                sent = await self.mailer.send(
                    message, f"{contact.token}@{self.settings.reply_domain}", [recipient.email]
                )
            except RetryableError:
                unsent = cost - index
                await self.quota.refund_global(unsent)
                await self.quota.refund_user(owner.id, "forward", unsent)
                raise
            except PermanentSendError:
                # The provider's error text may contain addresses, so only ids are logged.
                logger.warning("forward rejected", extra={"recipient_id": str(recipient.id)})
                await self.quota.refund_global(1)
                await self.quota.refund_user(owner.id, "forward", 1)
                continue
            provider_id = provider_id or sent
            delivered += 1
            await self.redis.sadd(done_key, str(recipient.id))
            await self.redis.expire(done_key, DONE_TTL_SECONDS)
        if not delivered:
            return await self._log(
                Outcome.DISCARDED, "send_failed", env, alias, contact, None, score
            )
        return await self._log(Outcome.DELIVERED, None, env, alias, contact, provider_id, score)
