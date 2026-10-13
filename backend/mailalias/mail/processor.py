"""MailProcessor: pull inbound jobs, process them with bounded concurrency, then ack or retry."""

# 1st party imports
import asyncio
import contextlib
import logging
import signal
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

# 3rd party imports
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.config import Settings
from mailalias.integrations.cloudflare_queue import InboxSource
from mailalias.integrations.r2 import ObjectStore, R2ObjectMissing
from mailalias.integrations.rspamd import SpamChecker
from mailalias.mail.classifier import classify
from mailalias.mail.handlers.bounce import BounceHandler
from mailalias.mail.handlers.forward import ForwardHandler
from mailalias.mail.handlers.reply import ReplyHandler
from mailalias.mail.outbound import OutboundMailer
from mailalias.mail.types import HandlerResult, InboundEnvelope, MailKind, RetryableError
from mailalias.services.system_mail import SystemMailService

logger = logging.getLogger(__name__)

HEARTBEAT_KEY = "hb:processor"
HEARTBEAT_TTL_SECONDS = 120
IDLE_SLEEP_SECONDS = 5.0
PULL_ERROR_SLEEP_SECONDS = 15.0
MAX_RETRY_DELAY_SECONDS = 3600


def retry_delay(attempts: int, requested: int | None = None) -> int:
    """Redelivery delay: the handler's request, else exponential backoff from 60 s.

    Args:
        attempts: Delivery attempts so far (0 on first delivery).
        requested: Delay asked for by a RetryableError.
    Returns:
        Seconds, capped at one hour.
    """
    if requested is not None:
        return min(requested, MAX_RETRY_DELAY_SECONDS)
    return min(60 * (1 << min(attempts, 10)), MAX_RETRY_DELAY_SECONDS)


def parse_message(raw: bytes) -> EmailMessage:
    """Parse raw RFC 5322 bytes with the modern email policy.

    Args:
        raw: Message bytes.
    Returns:
        The EmailMessage.
    """
    return BytesParser(policy=policy.default).parsebytes(raw)


class MailProcessor:
    """Long-running consumer of the inbound queue."""

    def __init__(
        self,
        inbox: InboxSource,
        mailer: OutboundMailer,
        session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
        settings: Settings,
        redis: Redis,
        system_mail: SystemMailService,
        *,
        spam: SpamChecker | None,
        storage: ObjectStore,
    ) -> None:
        """Build the processor.

        Args:
            inbox: Queue + R2 source.
            mailer: Outbound mailer for forwards and replies.
            session_factory: Creates one DB session per message.
            settings: Batch size, concurrency, visibility timeout.
            redis: Redis (heartbeat, quotas).
            system_mail: Owner notices.
            spam: Spam scorer (None: forwards carry a "spam-check-unavailable" notice).
            storage: Object store for quarantined messages.
        Returns:
            None.
        """
        self.spam = spam
        self.storage = storage
        self.inbox = inbox
        self.mailer = mailer
        self.session_factory = session_factory
        self.settings = settings
        self.redis = redis
        self.system_mail = system_mail
        self.stopping = asyncio.Event()
        self.semaphore = asyncio.Semaphore(settings.processor_concurrency)

    async def dispatch(
        self, kind: MailKind, env: InboundEnvelope, msg: EmailMessage, raw: bytes
    ) -> HandlerResult | None:
        """Run the handler for a classified message.

        Args:
            kind: Classifier result.
            env: Envelope.
            msg: Parsed message.
            raw: Raw bytes (spam scanning and quarantine).
        Returns:
            The handler result, or None for DROP.
        """
        if kind == MailKind.DROP:
            return None
        async with self.session_factory() as db:
            args = (db, self.settings, self.mailer, self.redis, self.system_mail)
            if kind == MailKind.FORWARD:
                forward = ForwardHandler(*args, spam=self.spam, storage=self.storage)
                return await forward.handle(env, msg, raw)
            if kind == MailKind.REPLY:
                return await ReplyHandler(*args).handle(env, msg)
            return await BounceHandler(*args).handle(env, msg)

    async def process_one(self, env: InboundEnvelope) -> None:
        """Fetch, classify and handle one message, then ack (success) or retry (failure).

        Args:
            env: Envelope.
        Returns:
            None. Never raises.
        """
        log_extra = {"r2_key": env.r2_key, "attempts": env.attempts}
        try:
            try:
                raw = await self.inbox.fetch_raw(env.r2_key)
            except R2ObjectMissing:
                # Already processed (ack was lost) or expired by the lifecycle rule.
                logger.warning("raw message missing; acking", extra=log_extra)
                await self.inbox.ack([env.lease_id])
                return
            msg = parse_message(raw)
            kind = classify(env, msg, self.settings)
            result = await self.dispatch(kind, env, msg, raw)
            await self.inbox.delete_raw(env.r2_key)
            await self.inbox.ack([env.lease_id])
            logger.info(
                "processed",
                extra={
                    **log_extra,
                    "kind": kind.value,
                    "outcome": result.outcome.value if result else "dropped",
                    "reason": result.reason if result else None,
                },
            )
        except RetryableError as exc:
            delay = retry_delay(env.attempts, exc.delay_seconds)
            logger.warning("retrying", extra={**log_extra, "error": str(exc), "delay": delay})
            await self._retry(env, delay)
        except Exception as exc:  # unexpected: let the queue retry, then dead-letter
            delay = retry_delay(env.attempts)
            logger.exception(
                "processing failed", extra={**log_extra, "error_type": type(exc).__name__}
            )
            await self._retry(env, delay)

    async def _retry(self, env: InboundEnvelope, delay: int) -> None:
        """Ask the queue to redeliver; failures only log (the lease expiry retries anyway).

        Args:
            env: Envelope.
            delay: Seconds.
        Returns:
            None.
        """
        try:
            await self.inbox.retry([env.lease_id], delay)
        except Exception:
            logger.exception("retry request failed", extra={"r2_key": env.r2_key})

    async def _bounded(self, env: InboundEnvelope) -> None:
        """process_one under the concurrency semaphore.

        Args:
            env: Envelope.
        Returns:
            None.
        """
        async with self.semaphore:
            await self.process_one(env)

    async def heartbeat(self) -> None:
        """Record liveness for the admin health page and the monitor.

        Returns:
            None.
        """
        try:
            await self.redis.set(
                HEARTBEAT_KEY, datetime.now(UTC).isoformat(), ex=HEARTBEAT_TTL_SECONDS
            )
        except Exception:
            logger.exception("heartbeat failed")

    async def run_once(self) -> int:
        """Pull one batch and process it fully.

        Returns:
            Number of messages pulled.
        """
        await self.heartbeat()
        envelopes = await self.inbox.pull(
            self.settings.processor_batch, self.settings.processor_visibility_ms
        )
        await asyncio.gather(*(self._bounded(env) for env in envelopes))
        return len(envelopes)

    async def _pause(self, seconds: float) -> None:
        """Sleep unless asked to stop.

        Args:
            seconds: Maximum sleep.
        Returns:
            None.
        """
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.stopping.wait(), seconds)

    async def run_forever(self) -> None:
        """Loop until SIGTERM/SIGINT; in-flight batches finish before exiting.

        Returns:
            None.
        """
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.stopping.set)
        logger.info("processor started")
        while not self.stopping.is_set():
            try:
                pulled = await self.run_once()
            except RetryableError as exc:
                logger.warning("pull failed", extra={"error": str(exc)})
                await self._pause(PULL_ERROR_SLEEP_SECONDS)
                continue
            if not pulled:
                await self._pause(IDLE_SLEEP_SECONDS)
        logger.info("processor stopped")
