"""Spam screening in the forward path, quarantine release/delete, and the quarantine API."""

# 1st party imports
import socket

# 3rd party imports
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.deps import get_storage
from mailalias.config import get_settings
from mailalias.db import get_redis
from mailalias.integrations.rspamd import RspamdClient
from mailalias.mail.auth_results import client_info
from mailalias.mail.handlers.forward import ForwardHandler
from mailalias.mail.processor import parse_message
from mailalias.mail.transform.headers import NOTICE_HEADER
from mailalias.mail.types import HandlerResult, InboundEnvelope, Outcome
from mailalias.models import AliasState, QuarantineItem
from mailalias.security.crypto import decrypt_bytes
from mailalias.services.quarantine import RELEASE_TASK, QuarantineService
from mailalias.services.system_mail import SystemMailService
from tests.eml import EML_DIR
from tests.integration.harness import Harness, mail_logs, make_harness

pytestmark = pytest.mark.usefixtures("dispatched")
GTUBE = "XJS*C4JBQADN1.NSBN3*2IDNEN*GTUBE-STANDARD-ANTI-UBE-TEST-EMAIL*C.34X"


async def _items(session: AsyncSession, h: Harness) -> list[QuarantineItem]:
    """Quarantine rows of the harness user.

    Args:
        session: Test session.
        h: Harness.
    Returns:
        Rows.
    """
    query = select(QuarantineItem).where(QuarantineItem.user_id == h.user.id)
    return list(await session.scalars(query))


async def _release(session: AsyncSession, h: Harness, item: QuarantineItem) -> HandlerResult | None:
    """Run a release the way the worker task does, with the harness fakes.

    Args:
        session: Test session.
        h: Harness.
        item: Item to release.
    Returns:
        The forward result.
    """
    settings = get_settings()
    handler = ForwardHandler(
        session,
        settings,
        h.mailer,
        get_redis(),
        SystemMailService(h.notices, settings),
        storage=h.store,
    )

    async def forward(env: InboundEnvelope, raw: bytes) -> HandlerResult:
        """Forward without the spam screen."""
        return await handler.handle(env, parse_message(raw), raw, skip_spam=True)

    result = await QuarantineService(session, settings, h.store).release(item.id, forward)
    await session.commit()
    return result


async def test_clean_mail_is_delivered_and_scored_with_cloudflare_client_details(
    session: AsyncSession,
) -> None:
    """Below the threshold: delivered, score logged, IP/HELO passed to the scanner."""
    h = await make_harness(session)
    h.spam.score = 2.5
    h.enqueue("real_inbound_gmail.eml")
    await h.processor.run_once()
    assert len(h.mailer.sent) == 1 and NOTICE_HEADER not in h.mailer.sent[0].message
    assert h.spam.calls[0]["ip"] == "209.85.220.41"
    (log,) = await mail_logs(session, h)
    assert (log.outcome, log.spam_score) == (Outcome.DELIVERED, 2.5)


async def test_spam_is_quarantined_encrypted(session: AsyncSession) -> None:
    """Quarantine band: nothing sent; raw stored encrypted; row has sender and subject."""
    h = await make_harness(session)
    h.spam.score = 8.0
    h.enqueue("real_inbound_gmail.eml")
    await h.processor.run_once()
    assert h.mailer.sent == []
    (item,) = await _items(session, h)
    assert (item.sender, item.subject, item.spam_score) == (
        "alice@gmail.com",
        "Hello from Gmail",
        8,
    )
    stored = h.store.objects[item.r2_key]
    assert b"Hello from Gmail" not in stored
    assert b"Hello from Gmail" in decrypt_bytes(stored)
    (log,) = await mail_logs(session, h)
    assert (log.outcome, log.reason) == (Outcome.QUARANTINED, "spam")


async def test_high_score_is_discarded(session: AsyncSession) -> None:
    """At or above the discard score: dropped, nothing stored."""
    h = await make_harness(session)
    h.spam.score = 15.0
    h.enqueue("real_inbound_gmail.eml")
    await h.processor.run_once()
    assert h.mailer.sent == [] and h.store.objects == {}
    assert (await mail_logs(session, h))[0].reason == "spam"


async def test_dmarc_fail_with_reject_policy_is_quarantined(session: AsyncSession) -> None:
    """A p=reject domain failing DMARC is held even with a low score."""
    h = await make_harness(session)
    h.enqueue(
        "real_inbound_gmail.eml",
        **{
            "dmarc=pass header.from=gmail.com policy.dmarc=none": (
                "dmarc=fail header.from=gmail.com policy.dmarc=reject"
            )
        },
    )
    await h.processor.run_once()
    assert h.mailer.sent == []
    assert (await mail_logs(session, h))[0].reason == "dmarc_reject"


async def test_scanner_down_delivers_with_notice(session: AsyncSession) -> None:
    """Rspamd unavailable: delivered anyway, flagged in a header."""
    h = await make_harness(session)
    h.spam.score = None
    h.enqueue("real_inbound_gmail.eml")
    await h.processor.run_once()
    (sent,) = h.mailer.sent
    assert sent.message[NOTICE_HEADER] == "spam-check-unavailable"


async def test_release_delivers_once_and_keeps_copy_when_alias_inactive(
    session: AsyncSession,
) -> None:
    """Inactive alias: nothing sent, copy kept. Active: delivered, copy removed, not twice."""
    h = await make_harness(session)
    h.spam.score = 8.0
    h.enqueue("real_inbound_gmail.eml")
    await h.processor.run_once()
    (item,) = await _items(session, h)
    h.alias.state = AliasState.INACTIVE
    await session.commit()
    assert (await _release(session, h, item)).outcome == Outcome.DISCARDED  # type: ignore[union-attr]
    assert item.released_at is None and item.r2_key in h.store.objects
    h.alias.state = AliasState.ACTIVE
    await session.commit()
    assert (await _release(session, h, item)).outcome == Outcome.DELIVERED  # type: ignore[union-attr]
    assert item.released_at is not None and h.store.objects == {}
    assert await _release(session, h, item) is None
    assert len(h.mailer.sent) == 1 and h.spam.calls == [h.spam.calls[0]]


@pytest.mark.usefixtures("relaxed_rate_limits")
async def test_quarantine_api(
    app: FastAPI,
    client: httpx.AsyncClient,
    session: AsyncSession,
    dispatched: list[tuple[str, str]],
) -> None:
    """List, queue a release, refuse strangers, delete."""
    h = await make_harness(session)
    app.dependency_overrides[get_storage] = lambda: h.store
    h.spam.score = 8.0
    h.enqueue("real_inbound_gmail.eml")
    h.enqueue("real_inbound_gmail.eml")
    await h.processor.run_once()
    login = await client.post("/api/v1/auth/login", json={"username": "pia", "password": "x" * 12})
    assert login.status_code == 200
    listed = (await client.get("/api/v1/quarantine")).json()
    assert len(listed) == 2 and listed[0]["alias_address"] == h.alias.address
    first, second = listed[0]["id"], listed[1]["id"]
    released = await client.post(f"/api/v1/quarantine/{first}/release")
    assert released.status_code == 202
    assert (RELEASE_TASK, first) in dispatched
    assert (await client.delete(f"/api/v1/quarantine/{second}")).status_code == 204
    assert len(h.store.objects) == 1
    missing = await client.post(f"/api/v1/quarantine/{second}/release")
    assert missing.status_code == 404


def _rspamd_up() -> bool:
    """Whether the dev Rspamd is listening.

    Returns:
        True if port 11333 accepts connections.
    """
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", 11333)) == 0


@pytest.mark.skipif(not _rspamd_up(), reason="dev Rspamd not running (make dev-up)")
async def test_gtube_lands_in_quarantine_band_with_real_rspamd() -> None:
    """With the client details the handler passes, GTUBE scores in the quarantine band."""
    settings = get_settings().model_copy(update={"rspamd_url": "http://localhost:11333"})
    raw = (
        (EML_DIR / "real_inbound_gmail.eml")
        .read_bytes()
        .replace(b"Hi there, this is a test message.", GTUBE.encode(), 1)
    )
    assert GTUBE.encode() in raw
    client = RspamdClient(settings)
    try:
        ip, helo = client_info(parse_message(raw))
        verdict = await client.check(raw, "alice@gmail.com", "spike@closetcompute.online", ip, helo)
    finally:
        await client.aclose()
    assert "CLOSET_GTUBE" in verdict.symbols
    assert settings.spam_quarantine_score <= verdict.score < settings.spam_discard_score
