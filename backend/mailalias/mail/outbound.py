"""Outbound mail interface (contract), the test FakeMailer, and the mailer factories."""

# 1st party imports
import base64
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

# local imports
from mailalias.config import Settings, get_settings


class OutboundMailer(Protocol):
    """Sends fully built MIME messages."""

    async def send(self, message: EmailMessage, envelope_from: str, rcpt_to: list[str]) -> str:
        """Send a fully built MIME message. Returns the provider message id."""
        ...


class PermanentSendError(Exception):
    """The provider refused the message permanently (5xx); retrying will not help."""


@dataclass
class SentMessage:
    """One message captured by FakeMailer."""

    message: EmailMessage
    envelope_from: str
    rcpt_to: list[str]


@dataclass
class FakeMailer:
    """In-memory mailer for tests and local development."""

    sent: list[SentMessage] = field(default_factory=list)

    async def send(self, message: EmailMessage, envelope_from: str, rcpt_to: list[str]) -> str:
        """Record the message instead of sending it.

        Args:
            message: The MIME message.
            envelope_from: SMTP MAIL FROM.
            rcpt_to: SMTP RCPT TO list.
        Returns:
            A fake provider id.
        """
        self.sent.append(SentMessage(message, envelope_from, list(rcpt_to)))
        return f"fake-{len(self.sent)}"


class QueuedMailer:
    """Hands messages to the `mail.send_system_mail` Celery task (retried, cap-checked)."""

    async def send(self, message: EmailMessage, envelope_from: str, rcpt_to: list[str]) -> str:
        """Enqueue the message for background delivery.

        Args:
            message: The MIME message.
            envelope_from: SMTP MAIL FROM.
            rcpt_to: SMTP RCPT TO list.
        Returns:
            The Celery task id (the provider id is only known after sending).
        """
        # Deferred import: the Celery app module imports settings and integrations.
        from mailalias.tasks.celery_app import celery_app

        raw = base64.b64encode(message.as_bytes()).decode()
        result = celery_app.send_task("mail.send_system_mail", args=[raw, envelope_from, rcpt_to])
        return f"queued:{result.id}"


def get_direct_mailer(settings: Settings) -> OutboundMailer:
    """Mailer that sends immediately (processor, Celery tasks, CLI).

    Args:
        settings: App settings.
    Returns:
        A FakeMailer under APP_ENV=test, otherwise the Resend SMTP sender.
    """
    if settings.app_env == "test":
        return FakeMailer()
    from mailalias.integrations.resend_smtp import ResendSmtpSender  # avoids an import cycle

    return ResendSmtpSender(settings)


def get_mailer() -> OutboundMailer:
    """Mailer used by the API for system mail (FastAPI dependency; overridden in tests).

    Returns:
        A QueuedMailer, so API requests never wait on SMTP.
    """
    if get_settings().app_env == "test":
        return FakeMailer()
    return QueuedMailer()
