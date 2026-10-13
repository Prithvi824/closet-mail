"""Shared processor test harness: fake inbox, flaky mailer and a wired MailProcessor."""

# 1st party imports
import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any

# 3rd party imports
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.config import get_settings
from mailalias.db import get_redis
from mailalias.integrations.cloudflare_queue import QueueMetrics
from mailalias.integrations.r2 import R2ObjectMissing
from mailalias.integrations.rspamd import SpamCheckUnavailable, SpamVerdict
from mailalias.mail.outbound import FakeMailer
from mailalias.mail.processor import MailProcessor
from mailalias.mail.types import InboundEnvelope, RetryableError
from mailalias.models import Alias, MailLog, User
from mailalias.services.aliases import AliasService
from mailalias.services.system_mail import SystemMailService
from mailalias.services.users import UserService
from tests.eml import EML_DIR, envelope


@dataclass
class FakeInbox:
    """In-memory InboxSource recording acks, retries and deletions."""

    envelopes: list[InboundEnvelope] = field(default_factory=list)
    raw: dict[str, bytes] = field(default_factory=dict)
    acked: list[str] = field(default_factory=list)
    retried: list[tuple[str, int]] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    async def pull(self, batch_size: int, visibility_timeout_ms: int) -> list[InboundEnvelope]:
        """Hand out and clear the pending envelopes."""
        batch, self.envelopes = self.envelopes[:batch_size], self.envelopes[batch_size:]
        return batch

    async def fetch_raw(self, r2_key: str) -> bytes:
        """Return stored bytes or raise R2ObjectMissing."""
        if r2_key not in self.raw:
            raise R2ObjectMissing(r2_key)
        return self.raw[r2_key]

    async def ack(self, lease_ids: list[str]) -> None:
        """Record acks."""
        self.acked.extend(lease_ids)

    async def retry(self, lease_ids: list[str], delay_seconds: int) -> None:
        """Record retries."""
        self.retried.extend((lease, delay_seconds) for lease in lease_ids)

    async def delete_raw(self, r2_key: str) -> None:
        """Record deletions."""
        self.deleted.append(r2_key)


@dataclass
class FakeStore:
    """In-memory ObjectStore."""

    objects: dict[str, bytes] = field(default_factory=dict)

    async def get(self, key: str) -> bytes:
        """Return the object or raise R2ObjectMissing."""
        if key not in self.objects:
            raise R2ObjectMissing(key)
        return self.objects[key]

    async def put(self, key: str, data: bytes) -> None:
        """Store the object."""
        self.objects[key] = data

    async def delete(self, key: str) -> None:
        """Delete the object if present."""
        self.objects.pop(key, None)


@dataclass
class FakeSpam:
    """SpamChecker returning a fixed score (None: scanner unavailable); records calls."""

    score: float | None = 0.0
    calls: list[dict[str, str | None]] = field(default_factory=list)

    async def check(
        self, raw: bytes, mail_from: str, rcpt: str, ip: str | None, helo: str | None
    ) -> SpamVerdict:
        """Return the configured verdict."""
        self.calls.append({"mail_from": mail_from, "rcpt": rcpt, "ip": ip, "helo": helo})
        if self.score is None:
            raise SpamCheckUnavailable("ConnectError")
        return SpamVerdict(self.score, ())


@dataclass
class FakeQueues:
    """CloudflareQueueAdmin stand-in recording sends and acks."""

    dlq: list[dict[str, Any]] = field(default_factory=list)
    backlog: dict[str, int] = field(default_factory=dict)
    sent: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    acked: list[str] = field(default_factory=list)
    down: bool = False

    async def metrics(self, queue_id: str) -> QueueMetrics:
        """Return the configured backlog (or fail when down)."""
        if self.down:
            raise RetryableError("cloudflare down")
        return QueueMetrics(self.backlog.get(queue_id, 0), 0)

    async def pull(
        self, queue_id: str, batch_size: int, visibility_timeout_ms: int
    ) -> list[dict[str, Any]]:
        """Return the DLQ messages."""
        return list(self.dlq)

    async def send(self, queue_id: str, body: dict[str, Any]) -> None:
        """Record a push."""
        self.sent.append((queue_id, body))

    async def ack(self, queue_id: str, lease_ids: list[str]) -> None:
        """Record acks."""
        self.acked.extend(lease_ids)


class FlakyMailer(FakeMailer):
    """Fails the first `failures` sends with the given exception, then succeeds."""

    def __init__(self, error: Exception, failures: int = 1) -> None:
        """Configure the failure.

        Args:
            error: Exception to raise.
            failures: How many sends fail.
        Returns:
            None.
        """
        super().__init__()
        self.error, self.failures = error, failures

    async def send(self, message: EmailMessage, envelope_from: str, rcpt_to: list[str]) -> str:
        """Raise until the failure budget is spent."""
        if self.failures:
            self.failures -= 1
            raise self.error
        return await super().send(message, envelope_from, rcpt_to)


@dataclass
class Harness:
    """A processor wired to fakes plus the objects tests inspect."""

    processor: MailProcessor
    inbox: FakeInbox
    mailer: FakeMailer
    notices: FakeMailer
    user: User
    alias: Alias
    spam: FakeSpam
    store: FakeStore

    def enqueue(
        self,
        fixture: str,
        rcpt_to: str | None = None,
        mail_from: str = "alice@gmail.com",
        **raw_overrides: str,
    ) -> str:
        """Queue a fixture addressed to the alias (or rcpt_to).

        Args:
            fixture: .eml file name.
            rcpt_to: Envelope recipient (defaults to the alias).
            mail_from: Envelope sender.
            raw_overrides: Text replacements applied to the raw bytes.
        Returns:
            The lease id.
        """
        raw = (EML_DIR / fixture).read_bytes()
        for old, new in raw_overrides.items():
            raw = raw.replace(old.encode(), new.encode())
        env = envelope(rcpt_to or self.alias.address, mail_from)
        lease = f"lease-{len(self.inbox.raw)}"
        env = InboundEnvelope(**{**env.__dict__, "lease_id": lease, "r2_key": f"in/{lease}.eml"})
        self.inbox.envelopes.append(env)
        self.inbox.raw[env.r2_key] = raw
        return lease


def _factory(session: AsyncSession) -> Callable[[], AbstractAsyncContextManager[AsyncSession]]:
    """Session factory that hands out the test's transactional session.

    Args:
        session: Test session.
    Returns:
        A callable returning an async context manager.
    """

    @contextlib.asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield session

    return factory


async def make_harness(session: AsyncSession, mailer: FakeMailer | None = None) -> Harness:
    """Create user "pia" with an alias and a processor around fakes.

    Args:
        session: Test session.
        mailer: Outbound mailer (FakeMailer by default).
    Returns:
        The harness.
    """
    settings = get_settings()
    user = await UserService(session).create_user("pia", "pia@example.com", "x" * 12)
    alias = await AliasService(session, settings).create(user, local_part="shop")
    await session.commit()
    inbox, notices, spam, store = FakeInbox(), FakeMailer(), FakeSpam(), FakeStore()
    mailer = mailer or FakeMailer()
    processor = MailProcessor(
        inbox=inbox,
        mailer=mailer,
        session_factory=_factory(session),
        settings=settings,
        redis=get_redis(),
        system_mail=SystemMailService(notices, settings),
        spam=spam,
        storage=store,
    )
    # All messages share the test's single session, so process them one at a time.
    processor.semaphore = asyncio.Semaphore(1)
    return Harness(processor, inbox, mailer, notices, user, alias, spam, store)


async def mail_logs(session: AsyncSession, harness: Harness) -> list[MailLog]:
    """Mail log rows of the harness user.

    Args:
        session: Test session.
        harness: Harness.
    Returns:
        Rows, oldest first.
    """
    query = select(MailLog).where(MailLog.user_id == harness.user.id).order_by(MailLog.created_at)
    return list(await session.scalars(query))
