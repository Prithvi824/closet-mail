"""Retention rules, monitor alerts with dedup, and the backup pipeline (fake pg_dump, real gpg)."""

# 1st party imports
import gzip
import os
import stat
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

# 3rd party imports
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.config import get_settings
from mailalias.db import get_redis
from mailalias.mail.outbound import FakeMailer
from mailalias.mail.processor import HEARTBEAT_KEY
from mailalias.mail.types import MailKind, Outcome
from mailalias.models import (
    DeliveryLog,
    FailedDelivery,
    FailureKind,
    Invite,
    MailLog,
    QuarantineItem,
    Recipient,
    SubdomainState,
    SubdomainStatus,
    UserRole,
)
from mailalias.security.crypto import lookup_hash
from mailalias.services.backup import BackupError, backup_key, pg_environment, run_backup
from mailalias.services.monitor import collect_alerts, send_alerts
from mailalias.services.quota import global_key, share_key
from mailalias.services.retention import run_retention
from mailalias.services.system_mail import SystemMailService
from mailalias.services.users import UserService
from tests.integration.harness import FakeQueues, FakeStore, make_harness

pytestmark = pytest.mark.usefixtures("dispatched")
NOW = datetime.now(UTC)


async def test_retention_rules(session: AsyncSession) -> None:
    """Old logs/failures, expired or released quarantine, expired invites and stale tokens go."""
    h = await make_harness(session)
    store = FakeStore({"quarantine/old.bin": b"x", "quarantine/new.bin": b"y"})
    common = {"user_id": h.user.id, "alias_id": h.alias.id, "sender": "a@b.c", "spam_score": 9.0}
    session.add_all(
        [
            QuarantineItem(
                **common, r2_key="quarantine/old.bin", expires_at=NOW - timedelta(minutes=1)
            ),
            QuarantineItem(
                **common, r2_key="quarantine/new.bin", expires_at=NOW + timedelta(days=3)
            ),
            MailLog(
                user_id=h.user.id,
                kind=MailKind.FORWARD,
                outcome=Outcome.DELIVERED,
                created_at=NOW - timedelta(days=91),
            ),
            MailLog(user_id=h.user.id, kind=MailKind.FORWARD, outcome=Outcome.DELIVERED),
            FailedDelivery(
                user_id=h.user.id, kind=FailureKind.SOFT, created_at=NOW - timedelta(days=91)
            ),
            FailedDelivery(user_id=h.user.id, kind=FailureKind.SOFT),
            Invite(
                email="x@example.org",
                email_hash=lookup_hash("x@example.org"),
                token_hash=uuid.uuid4().hex,
                expires_at=NOW - timedelta(days=1),
            ),
            Invite(
                email="y@example.org",
                email_hash=lookup_hash("y@example.org"),
                token_hash=uuid.uuid4().hex,
                expires_at=NOW - timedelta(days=1),
                used_at=NOW,
            ),
            Recipient(
                user_id=h.user.id,
                email="v@example.org",
                email_hash=lookup_hash("v@example.org"),
                verify_token_hash="stale",
                verify_sent_at=NOW - timedelta(hours=49),
            ),
        ]
    )
    await session.commit()
    result = await run_retention(session, store)
    await session.commit()
    assert (result.quarantine, result.mail_log, result.failed_deliveries) == (1, 1, 1)
    assert (result.invites, result.verify_tokens) == (1, 1)
    assert set(store.objects) == {"quarantine/new.bin"}
    assert (
        len((await session.scalars(select(MailLog).where(MailLog.user_id == h.user.id))).all()) == 1
    )
    again = await run_retention(session, store)
    assert sum(vars(again).values()) == 0


async def test_mail_log_and_its_deliveries_are_kept_for_90_days(session: AsyncSession) -> None:
    """An 89-day-old message stays with its deliveries; a 91-day-old one goes with its own."""
    h = await make_harness(session)
    logs = {}
    for age in (89, 91):
        log = MailLog(
            user_id=h.user.id,
            kind=MailKind.FORWARD,
            outcome=Outcome.DELIVERED,
            created_at=NOW - timedelta(days=age),
        )
        session.add(log)
        await session.flush()
        session.add(DeliveryLog(mail_log_id=log.id, user_id=h.user.id, provider_id=f"p-{age}"))
        logs[age] = log.id
    await session.commit()
    await run_retention(session, FakeStore())
    await session.commit()
    kept = (await session.scalars(select(DeliveryLog.provider_id))).all()
    assert kept == ["p-89"]
    assert await session.get(MailLog, logs[89]) is not None
    session.expunge_all()
    assert await session.get(MailLog, logs[91]) is None


async def test_monitor_alerts_and_dedup(session: AsyncSession) -> None:
    """Missing heartbeat, DLQ, send cap and bounce rate alert; each is mailed once per 6 h."""
    h = await make_harness(session)
    admin = await UserService(session).create_user(
        "boss", "boss@example.com", "x" * 12, UserRole.ADMIN
    )
    session.add(FailedDelivery(user_id=h.user.id, kind=FailureKind.HARD))
    await session.commit()
    settings = get_settings()
    redis = get_redis()
    await redis.delete(HEARTBEAT_KEY)
    await redis.set(global_key(), int(settings.outbound_daily_cap * 0.9))
    queues = FakeQueues(backlog={settings.cf_queue_id_dlq: 2})
    alerts = await collect_alerts(session, settings, redis, queues)  # type: ignore[arg-type]
    assert {a.key for a in alerts} == {"processor_down", "dlq", "send_cap", "bounce_rate"}
    mailer = FakeMailer()
    mail = SystemMailService(mailer, settings)
    assert await send_alerts(session, redis, mail, alerts) == 4
    # The harness user is an operator too, so both admins get the alerts.
    assert {m.rcpt_to[0] for m in mailer.sent} == {admin.email, h.user.email}
    assert await send_alerts(session, redis, mail, alerts) == 0


async def test_subdomain_alerts_once_per_subdomain_and_problem(session: AsyncSession) -> None:
    """DNS missing, no inbox and a used-up share alert per live subdomain; repeats are held."""
    operator = await UserService(session).create_user(
        "boss", "boss@example.com", "x" * 12, UserRole.ADMIN
    )
    users = {}
    for label in ("acme", "beta", "gamma", "delta", "omega"):
        users[label] = await UserService(session).create_user(
            label, f"{label}@example.com", "x" * 12
        )
    states = {
        "acme": SubdomainState.DNS_MISSING,
        "beta": SubdomainState.NO_INBOX,
        "delta": SubdomainState.DNS_MISSING,
        "omega": SubdomainState.DNS_MISSING,
    }
    for label, state in states.items():
        session.add(SubdomainStatus(user_id=users[label].id, state=state, checked_at=NOW))
    users["delta"].disabled_at = NOW
    users["omega"].retired_at = NOW
    await session.commit()
    redis = get_redis()
    await redis.set(HEARTBEAT_KEY, NOW.isoformat())
    await redis.set(share_key(users["gamma"].id), get_settings().subdomain_sends_per_day)
    alerts = await collect_alerts(session, get_settings(), redis, FakeQueues())  # type: ignore[arg-type]
    assert {a.key for a in alerts} == {
        "sub:acme:dns_missing",
        "sub:beta:no_inbox",
        "sub:gamma:share",
    }
    mailer = FakeMailer()
    mail = SystemMailService(mailer, get_settings())
    assert await send_alerts(session, redis, mail, alerts) == 3
    assert {m.rcpt_to[0] for m in mailer.sent} == {operator.email}
    assert await send_alerts(session, redis, mail, alerts) == 0


async def test_healthy_system_has_no_alerts(session: AsyncSession) -> None:
    """Fresh heartbeat, empty DLQ, low sends, no bounces: nothing to report."""
    await make_harness(session)
    redis = get_redis()
    await redis.set(HEARTBEAT_KEY, NOW.isoformat())
    alerts = await collect_alerts(session, get_settings(), redis, FakeQueues())  # type: ignore[arg-type]
    assert alerts == []


def test_pg_environment_keeps_password_out_of_argv() -> None:
    """Connection details go to PG* variables; the URL driver suffix is ignored."""
    env = pg_environment("postgresql+asyncpg://u:s3cret@db.internal:5544/mail")
    assert (env["PGHOST"], env["PGPORT"], env["PGUSER"], env["PGPASSWORD"], env["PGDATABASE"]) == (
        "db.internal",
        "5544",
        "u",
        "s3cret",
        "mail",
    )
    assert backup_key(datetime(2026, 10, 12, tzinfo=UTC)) == "backups/mailalias-20261012.sql.gz.gpg"


async def test_backup_pipeline_round_trip(tmp_path: Path) -> None:
    """A fake pg_dump's output comes back intact after gpg decrypt + gunzip."""
    fake_dump = tmp_path / "pg_dump"
    fake_dump.write_text(
        '#!/bin/sh\ntest -n "$PGPASSWORD" && echo "CREATE TABLE t (id int); -- $PGDATABASE"\n'
    )
    fake_dump.chmod(fake_dump.stat().st_mode | stat.S_IEXEC)
    settings = get_settings().model_copy(
        update={"pg_dump_bin": str(fake_dump), "backup_passphrase": SecretStr("correct horse")}
    )
    store = FakeStore()
    key = await run_backup(settings, store, NOW)
    encrypted = tmp_path / "b.gpg"
    encrypted.write_bytes(store.objects[key])
    with tempfile.TemporaryDirectory() as home:
        plain = subprocess.run(
            [
                "gpg",
                "--homedir",
                home,
                "--batch",
                "--pinentry-mode",
                "loopback",
                "--passphrase",
                "correct horse",
                "--decrypt",
                str(encrypted),
            ],
            check=True,
            capture_output=True,
        ).stdout
    assert gzip.decompress(plain).decode().startswith("CREATE TABLE t (id int);")
    assert b"CREATE TABLE" not in store.objects[key]


async def test_backup_failures_are_reported(tmp_path: Path) -> None:
    """No passphrase, or a failing pg_dump, raises BackupError and uploads nothing."""
    store = FakeStore()
    with pytest.raises(BackupError, match="BACKUP_PASSPHRASE"):
        await run_backup(get_settings().model_copy(update={"backup_passphrase": None}), store)
    failing = tmp_path / "pg_dump"
    failing.write_text("#!/bin/sh\necho 'connection refused' >&2\nexit 1\n")
    failing.chmod(0o755)
    settings = get_settings().model_copy(
        update={"pg_dump_bin": str(failing), "backup_passphrase": SecretStr("p")}
    )
    with pytest.raises(BackupError, match="connection refused"):
        await run_backup(settings, store)
    assert store.objects == {}
    assert os.environ.get("PGPASSWORD") is None
