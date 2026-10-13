"""Nightly database backup: pg_dump, gzip, GPG symmetric encryption, upload to R2 backups/."""

# 1st party imports
import asyncio
import gzip
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

# 3rd party imports
from sqlalchemy.engine import make_url

# local imports
from mailalias.config import Settings
from mailalias.integrations.r2 import ObjectStore

logger = logging.getLogger(__name__)

BACKUP_PREFIX = "backups/"
CHUNK_BYTES = 1 << 16
STDERR_TAIL_CHARS = 300


class BackupError(RuntimeError):
    """pg_dump or gpg failed (the message never contains credentials)."""


def backup_key(now: datetime) -> str:
    """Object key of the backup for a day.

    Args:
        now: Backup time.
    Returns:
        "backups/mailalias-YYYYMMDD.sql.gz.gpg".
    """
    return f"{BACKUP_PREFIX}mailalias-{now:%Y%m%d}.sql.gz.gpg"


def pg_environment(database_url: str) -> dict[str, str]:
    """libpq environment for the configured database (keeps the password out of argv).

    Args:
        database_url: SQLAlchemy URL (any driver).
    Returns:
        A copy of os.environ plus PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE.
    """
    url = make_url(database_url)
    env = dict(os.environ)
    values = {
        "PGHOST": url.host,
        "PGPORT": str(url.port) if url.port else None,
        "PGUSER": url.username,
        "PGPASSWORD": url.password,
        "PGDATABASE": url.database,
    }
    env.update({key: str(value) for key, value in values.items() if value})
    return env


async def _dump_gzipped(settings: Settings, target: Path) -> None:
    """Stream a plain-SQL pg_dump into a gzip file.

    Args:
        settings: database_url and pg_dump_bin.
        target: Output .sql.gz path.
    Returns:
        None. Raises BackupError on failure.
    """
    proc = await asyncio.create_subprocess_exec(
        settings.pg_dump_bin,
        "--no-owner",
        "--no-privileges",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=pg_environment(settings.database_url),
    )
    assert proc.stdout is not None and proc.stderr is not None
    with gzip.open(target, "wb") as out:
        while chunk := await proc.stdout.read(CHUNK_BYTES):
            out.write(chunk)
    stderr = (await proc.stderr.read()).decode(errors="replace")
    if await proc.wait() != 0:
        raise BackupError(f"pg_dump failed: {stderr[-STDERR_TAIL_CHARS:]}")


async def _encrypt(source: Path, target: Path, passphrase: str, home: Path) -> None:
    """Symmetrically encrypt a file with gpg (AES256), passphrase on stdin.

    Args:
        source: Plain file.
        target: Encrypted output.
        passphrase: BACKUP_PASSPHRASE.
        home: Empty GNUPGHOME (the user's keyring is never touched).
    Returns:
        None. Raises BackupError on failure.
    """
    proc = await asyncio.create_subprocess_exec(
        "gpg",
        "--homedir",
        str(home),
        "--batch",
        "--yes",
        "--symmetric",
        "--cipher-algo",
        "AES256",
        "--pinentry-mode",
        "loopback",
        "--passphrase-fd",
        "0",
        "--output",
        str(target),
        str(source),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate(passphrase.encode())
    if proc.returncode != 0:
        raise BackupError(f"gpg failed: {stderr.decode(errors='replace')[-STDERR_TAIL_CHARS:]}")


async def run_backup(settings: Settings, storage: ObjectStore, now: datetime | None = None) -> str:
    """Dump, compress, encrypt and upload today's backup.

    Args:
        settings: Database URL, pg_dump binary and BACKUP_PASSPHRASE.
        storage: R2 bucket (backups/ has a 30-day lifecycle rule).
        now: Override for tests.
    Returns:
        The uploaded object key. Raises BackupError.
    """
    if settings.backup_passphrase is None:
        raise BackupError("BACKUP_PASSPHRASE is not set")
    now = now or datetime.now(UTC)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "gnupg").mkdir(mode=0o700)
        dump = work / "dump.sql.gz"
        encrypted = work / "dump.sql.gz.gpg"
        await _dump_gzipped(settings, dump)
        await _encrypt(
            dump, encrypted, settings.backup_passphrase.get_secret_value(), work / "gnupg"
        )
        key = backup_key(now)
        await storage.put(key, encrypted.read_bytes())
    logger.info("backup uploaded", extra={"key": key})
    return key
