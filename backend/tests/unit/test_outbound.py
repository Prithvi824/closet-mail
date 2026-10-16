"""Tests for the Resend SMTP sender's error mapping and the queued mailer."""

# 1st party imports
import base64
from email.message import EmailMessage
from typing import Any

# 3rd party imports
import aiosmtplib
import pytest

# local imports
from mailalias.config import get_settings
from mailalias.integrations import resend_smtp
from mailalias.integrations.resend_smtp import ResendSmtpSender
from mailalias.mail.outbound import PermanentSendError, QueuedMailer
from mailalias.mail.types import RetryableError


def _message() -> EmailMessage:
    """Minimal message.

    Returns:
        An EmailMessage.
    """
    msg = EmailMessage()
    msg["From"] = "noreply@closetcompute.online"
    msg["To"] = "owner@example.com"
    msg["Subject"] = "hi"
    msg.set_content("body")
    return msg


class _FakeSmtp:
    """aiosmtplib.SMTP stand-in whose send_message returns or raises a configured outcome."""

    outcome: Any = None

    def __init__(self, **kwargs: Any) -> None:
        """Record connection options.

        Args:
            kwargs: Connection options.
        Returns:
            None.
        """
        self.kwargs = kwargs

    async def __aenter__(self) -> "_FakeSmtp":
        """Enter the session.

        Returns:
            Self.
        """
        if isinstance(_FakeSmtp.outcome, OSError):
            raise _FakeSmtp.outcome
        return self

    async def __aexit__(self, *args: object) -> None:
        """Leave the session.

        Args:
            args: Exception info.
        Returns:
            None.
        """

    async def login(self, user: str, password: str) -> None:
        """Pretend to log in.

        Args:
            user: Username.
            password: Password.
        Returns:
            None.
        """

    async def send_message(self, *args: Any, **kwargs: Any) -> tuple[dict[str, Any], str]:
        """Return or raise the configured outcome.

        Args:
            args: Ignored.
            kwargs: Ignored.
        Returns:
            (errors, response text).
        """
        if isinstance(_FakeSmtp.outcome, Exception):
            raise _FakeSmtp.outcome
        return {}, _FakeSmtp.outcome


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the SMTP client used by the sender.

    Args:
        monkeypatch: Pytest monkeypatch.
    Returns:
        None.
    """
    monkeypatch.setattr(resend_smtp.aiosmtplib, "SMTP", _FakeSmtp)


async def test_success_returns_resend_id() -> None:
    """The 250 text (Resend email id) is returned stripped.

    Returns:
        None.
    """
    _FakeSmtp.outcome = " 01a12a6f-389f-79a4-80ea-3119259beb65 "
    sender = ResendSmtpSender(get_settings())
    assert (
        await sender.send(_message(), "a@b.c", ["d@e.f"]) == "01a12a6f-389f-79a4-80ea-3119259beb65"
    )


@pytest.mark.parametrize(
    ("outcome", "error"),
    [
        (aiosmtplib.SMTPDataError(451, "try later"), RetryableError),
        (aiosmtplib.SMTPDataError(550, "domain not verified"), PermanentSendError),
        (aiosmtplib.SMTPServerDisconnected("gone"), RetryableError),
        (ConnectionRefusedError("down"), RetryableError),
        (
            aiosmtplib.SMTPRecipientsRefused(
                [aiosmtplib.SMTPRecipientRefused(550, "no such user", "d@e.f")]
            ),
            PermanentSendError,
        ),
        (
            aiosmtplib.SMTPRecipientsRefused(
                [aiosmtplib.SMTPRecipientRefused(450, "mailbox busy", "d@e.f")]
            ),
            RetryableError,
        ),
    ],
)
async def test_error_mapping(outcome: Exception, error: type[Exception]) -> None:
    """4xx/connection errors are retryable; 5xx are permanent.

    Args:
        outcome: Simulated SMTP failure.
        error: Expected exception type.
    Returns:
        None.
    """
    _FakeSmtp.outcome = outcome
    with pytest.raises(error):
        await ResendSmtpSender(get_settings()).send(_message(), "a@b.c", ["d@e.f"])


async def test_queued_mailer_enqueues_raw_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """QueuedMailer sends the base64 MIME, envelope sender and recipients to Celery.

    Args:
        monkeypatch: Pytest monkeypatch.
    Returns:
        None.
    """
    from mailalias.tasks.celery_app import celery_app

    calls: list[tuple[str, list[Any]]] = []

    class _Result:
        id = "task-1"

    def _send_task(name: str, args: list[Any]) -> _Result:
        calls.append((name, args))
        return _Result()

    monkeypatch.setattr(celery_app, "send_task", _send_task)
    message = _message()
    assert await QueuedMailer().send(message, "noreply@x", ["o@e.com"]) == "queued:task-1"
    name, (raw, envelope_from, rcpt) = calls[0]
    assert name == "mail.send_system_mail"
    assert base64.b64decode(raw) == message.as_bytes()
    assert (envelope_from, rcpt) == ("noreply@x", ["o@e.com"])
