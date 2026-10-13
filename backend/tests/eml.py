"""Helpers for loading .eml fixtures and building inbound envelopes in tests."""

# 1st party imports
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from typing import cast

# local imports
from mailalias.mail.types import InboundEnvelope

EML_DIR = Path(__file__).parent / "fixtures" / "eml"


def load_eml(name: str) -> EmailMessage:
    """Parse a fixture from tests/fixtures/eml with the modern email policy.

    Args:
        name: File name, e.g. "real_inbound_gmail.eml".
    Returns:
        The parsed message.
    """
    raw = (EML_DIR / name).read_bytes()
    return cast(EmailMessage, BytesParser(policy=policy.default).parsebytes(raw))


def envelope(rcpt_to: str, mail_from: str = "alice@gmail.com") -> InboundEnvelope:
    """Build an InboundEnvelope for handler/classifier tests.

    Args:
        rcpt_to: Envelope recipient.
        mail_from: Envelope sender ("" for the null sender).
    Returns:
        The envelope.
    """
    return InboundEnvelope(
        lease_id="lease-1",
        attempts=0,
        r2_key="in/2026/10/11/test.eml",
        mail_from=mail_from,
        rcpt_to=rcpt_to,
        raw_size=1024,
        received_at=datetime(2026, 10, 11, tzinfo=UTC),
    )
