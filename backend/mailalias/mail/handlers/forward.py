"""ForwardHandler: deliver mail sent to an alias to the owner's recipients via the reply token."""

# 1st party imports
import asyncio
import logging
import uuid
from collections.abc import Sequence
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
from mailalias.services.mail_log import RELEASED, DeliveryRecord
from mailalias.services.notices import operator_addresses, send_notice
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
    released: bool = False  # released from quarantine: already counted as received


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
        *,
        sender: str | None = None,
        user_id: uuid.UUID | None = None,
        deliveries: Sequence[DeliveryRecord] = (),
        count_usage: bool = True,
    ) -> HandlerResult:
        """Write the mail log, commit, and build the result.

        Args:
            outcome, reason, env, alias, contact: What happened, envelope, resolved objects.
            provider_id, spam_score, deliveries: First send's id, Rspamd score, one record per send.
            sender, user_id, count_usage: Sender address, owner when no alias, False on redelivery.
        Returns:
            The HandlerResult.
        """
        await mail_log.record(
            self.db,
            kind=MailKind.FORWARD,
            outcome=outcome,
            reason=reason,
            user_id=alias.user_id if alias else user_id,
            alias_id=alias.id if alias else None,
            contact_id=contact.id if contact else None,
            size_bytes=env.raw_size,
            provider_id=provider_id,
            spam_score=spam_score,
            received_at=env.received_at,
            sender_address=sender,
            deliveries=deliveries,
            count_usage=count_usage,
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
        sender: str,
    ) -> HandlerResult | None:
        """Discard or quarantine spam (and DMARC failures of p=reject domains).

        Args:
            env, msg, raw: The inbound message.
            alias, contact: Resolved objects.
            score, sender: Rspamd score (None if unavailable); sender address.
        Returns:
            A final result when the message was discarded or held, else None (deliver).
        """
        if score is not None and score >= self.settings.spam_discard_score:
            return await self._log(
                Outcome.DISCARDED, "spam", env, alias, contact, None, score, sender=sender
            )
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
        return await self._log(
            Outcome.QUARANTINED, reason, env, alias, contact, None, score, sender=sender
        )

    async def _subdomain_owner(self, domain: str) -> User | None:
        """The subdomain (user) whose label is the first label of a personal-subdomain domain.

        Args:
            domain: Recipient domain, e.g. "acme.closetcompute.online".
        Returns:
            The user, or None for the shared domain or an unknown label.
        """
        label = domain.removesuffix("." + self.settings.alias_domain)
        if label == domain:
            return None
        return await self.db.scalar(select(User).where(User.username == label))

    async def _resolve_alias(self, address: str) -> tuple[Alias | None, str]:
        """Load the alias, auto-creating it on a subdomain with catch-all on (capped per day).

        Args:
            address: Normalised recipient address.
        Returns:
            (alias with recipients loaded, or None; drop reason when None).
        """
        query = (
            select(Alias).options(selectinload(Alias.recipients)).where(Alias.address == address)
        )
        alias = await self.db.scalar(query)
        if alias is not None:
            return alias, ""
        local, domain = split_address(address)
        owner = await self._subdomain_owner(domain)
        if owner is None or not owner.subdomain_catchall or owner.disabled_at is not None:
            return None, "unknown_alias"
        # A daily cap (not the hourly UI limit) keeps a spam run from flooding alias rows and KV.
        if not await self.quota.consume_catchall(owner.id, owner.limits):
            await self._notify_catchall_limit(owner)
            return None, "catchall_limit"
        try:
            # Catch-all creation follows incoming mail, so the hourly create limit does not apply.
            await AliasService(self.db, self.settings, self.redis).create(
                owner, local_part=local, subdomain=True, enforce_rate=False
            )
        except Conflict:
            # Another message for the same new address created it first; load that one below.
            pass
        except DomainError as exc:
            logger.info("catch-all alias not created", extra={"code": exc.code})
            return None, "unknown_alias"
        await self.db.commit()
        return await self.db.scalar(query.execution_options(populate_existing=True)), ""

    async def _recipients(self, alias: Alias, owner: User) -> list[Recipient]:
        """Usable recipients of the alias, falling back to all of the owner's default inboxes.

        Args:
            alias: Alias with recipients loaded.
            owner: Alias owner.
        Returns:
            Recipients (never on a service domain).
        """
        recipients = [r for r in alias.recipients if r.is_usable]
        if not recipients:
            defaults = await self.db.scalars(
                select(Recipient)
                .where(Recipient.user_id == owner.id, Recipient.forward_by_default.is_(True))
                .order_by(Recipient.created_at)
            )
            recipients = [r for r in defaults if r.is_usable]
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
        """Tell the operator (at most once a day per subdomain) that forwards are being dropped.

        Args:
            owner: Alias owner (the subdomain).
        Returns:
            None.
        """
        await send_notice(
            self.redis,
            self.system_mail,
            await operator_addresses(self.db),
            throttle_key=f"quota:{owner.id}:{datetime.now(UTC):%Y%m%d}",
            ttl_seconds=QUOTA_NOTICE_TTL_SECONDS,
            subject=f"Forwarding limit reached for {owner.username}",
            body=(
                f"The hourly forwarding limit of {owner.username} was reached, so some "
                "messages were not forwarded. Forwarding resumes automatically next hour."
            ),
        )

    async def _notify_share(self, owner: User) -> None:
        """Tell the operator (at most once a day per subdomain) that its send share is used up.

        Args:
            owner: Alias owner (the subdomain).
        Returns:
            None.
        """
        await send_notice(
            self.redis,
            self.system_mail,
            await operator_addresses(self.db),
            throttle_key=f"share:{owner.id}:{datetime.now(UTC):%Y%m%d}",
            ttl_seconds=QUOTA_NOTICE_TTL_SECONDS,
            subject=f"Daily send share used up for {owner.username}",
            body=(
                f"{owner.username} has used its daily share of sends. Its mail is queued and "
                "will be delivered after midnight UTC, or sooner if you raise its share."
            ),
        )

    async def _notify_catchall_limit(self, owner: User) -> None:
        """Tell the operator (at most once a day per subdomain) that catch-all mail is dropped.

        Args:
            owner: The subdomain.
        Returns:
            None.
        """
        await send_notice(
            self.redis,
            self.system_mail,
            await operator_addresses(self.db),
            throttle_key=f"catchall:{owner.id}:{datetime.now(UTC):%Y%m%d}",
            ttl_seconds=QUOTA_NOTICE_TTL_SECONDS,
            subject=f"Catch-all limit reached for {owner.username}",
            body=(
                f"{owner.username} received mail for more new addresses today than its catch-all "
                "limit allows, so mail to further new addresses is dropped until midnight UTC. "
                "This usually means a spam run; raise the limit in its settings if it is real mail."
            ),
        )

    async def _refund(self, owner_id: uuid.UUID, cost: int) -> None:
        """Give back every quota a send consumed when it did not happen.

        Args:
            owner_id: Subdomain id.
            cost: Sends to give back.
        Returns:
            None.
        """
        await self.quota.refund_global(cost)
        await self.quota.refund_share(owner_id, cost)
        await self.quota.refund_user(owner_id, "forward", cost)

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
        alias, drop_reason = await self._resolve_alias(normalize(env.rcpt_to))
        if alias is None or alias.user_id is None:
            # Attribute drops on a known subdomain to it, so its metrics show the lost mail.
            owner = (
                None
                if alias
                else await self._subdomain_owner(split_address(normalize(env.rcpt_to))[1])
            )
            return await self._log(
                Outcome.DISCARDED,
                drop_reason or "unknown_alias",
                env,
                alias,
                sender=address,
                user_id=owner.id if owner else None,
            )
        if alias.state != AliasState.ACTIVE:
            reason = "alias_inactive" if alias.state == AliasState.INACTIVE else "alias_deleted"
            return await self._log(Outcome.DISCARDED, reason, env, alias, sender=address)
        owner = await self.db.get(User, alias.user_id)
        if owner is None or owner.disabled_at is not None:
            return await self._log(Outcome.DISCARDED, "user_disabled", env, alias, sender=address)
        # Our own forwards coming back (e.g. a recipient forwarding to an alias) would loop.
        if msg.get(ALIAS_HEADER) or (
            address and is_service_domain(split_address(address)[1], self.settings.reply_domain)
        ):
            return await self._log(Outcome.DISCARDED, "loop", env, alias, sender=address)
        if not address:
            return await self._log(Outcome.DISCARDED, "no_sender", env, alias)
        recipients = await self._recipients(alias, owner)
        if not recipients:
            return await self._log(Outcome.DISCARDED, "no_recipient", env, alias, sender=address)

        if await BlocklistService(self.db).is_blocked(owner.id, address):
            return await self._log(Outcome.BLOCKED, "blocklist", env, alias, sender=address)
        contact = await ContactService(self.db).get_or_create(alias, address, name)
        # Commit now so the reply token in the delivered mail exists even if a later step fails.
        await self.db.commit()
        if contact.blocked:
            return await self._log(
                Outcome.BLOCKED, "contact_blocked", env, alias, contact, sender=address
            )
        score: float | None = None
        unchecked = False
        if not skip_spam:
            raw = raw if raw is not None else msg.as_bytes()
            score = await self._spam_score(env, msg, raw)
            unchecked = score is None
            held = await self._screen(env, msg, raw, alias, contact, score, address)
            if held is not None:
                return held
        delivery = Delivery(
            alias, owner, contact, recipients, address, name, score, unchecked, skip_spam
        )
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
        if cost and not await self.quota.check_share(owner.id, cost, owner.limits):
            # Over its share the subdomain waits like the global cap, so others keep sending.
            await self.quota.refund_global(cost)
            await self._notify_share(owner)
            raise RetryableError("subdomain send share reached", cap_retry_delay())
        if cost and not await self.quota.check_and_consume(
            owner.id, "forward", cost, limits=owner.limits
        ):
            await self.quota.refund_global(cost)
            await self.quota.refund_share(owner.id, cost)
            await self._notify_quota(owner)
            return await self._log(
                Outcome.DISCARDED,
                "quota",
                env,
                alias,
                contact,
                None,
                score,
                sender=delivery.address,
            )

        display = sender_display(delivery.address, delivery.name)
        records: list[DeliveryRecord] = []
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
                await self._refund(owner.id, 1)
                continue
            if delivery.spam_unchecked:
                message[NOTICE_HEADER] = "spam-check-unavailable"
            try:
                sent = await self.mailer.send(
                    message, f"{contact.token}@{self.settings.reply_domain}", [recipient.email]
                )
            except RetryableError:
                await self._refund(owner.id, cost - index)
                raise
            except PermanentSendError:
                # The provider's error text may contain addresses, so only ids are logged.
                logger.warning("forward rejected", extra={"recipient_id": str(recipient.id)})
                await self._refund(owner.id, 1)
                continue
            records.append(DeliveryRecord(recipient.id, sent))
            delivered += 1
            await self.redis.sadd(done_key, str(recipient.id))
            await self.redis.expire(done_key, DONE_TTL_SECONDS)
        if not delivered:
            return await self._log(
                Outcome.DISCARDED,
                "send_failed",
                env,
                alias,
                contact,
                None,
                score,
                sender=delivery.address,
            )
        # cost == 0: every inbox got it on an earlier attempt, which was already counted.
        return await self._log(
            Outcome.DELIVERED,
            RELEASED if delivery.released else None,
            env,
            alias,
            contact,
            records[0].provider_id if records else None,
            score,
            sender=delivery.address,
            deliveries=records,
            count_usage=cost > 0,
        )
