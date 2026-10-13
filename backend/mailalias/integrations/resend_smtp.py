"""Resend SMTP relay sender (implicit TLS on 465)."""

# 1st party imports
import logging
from email.message import EmailMessage

# 3rd party imports
import aiosmtplib

# local imports
from mailalias.config import Settings
from mailalias.mail.outbound import PermanentSendError
from mailalias.mail.types import RetryableError

logger = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 30


class ResendSmtpSender:
    """OutboundMailer that relays through smtp.resend.com, one connection per message."""

    def __init__(self, settings: Settings) -> None:
        """Build the sender.

        Args:
            settings: Resend host, port and API key.
        Returns:
            None.
        """
        self._host = settings.resend_smtp_host
        self._port = settings.resend_smtp_port
        self._password = settings.resend_api_key.get_secret_value()

    async def send(self, message: EmailMessage, envelope_from: str, rcpt_to: list[str]) -> str:
        """Send one message.

        Args:
            message: Fully built MIME message.
            envelope_from: SMTP MAIL FROM.
            rcpt_to: SMTP RCPT TO list.
        Returns:
            The Resend email id (the 250 response text, verified in T4).
            Raises RetryableError (4xx/connection) or PermanentSendError (5xx).
        """
        smtp = aiosmtplib.SMTP(
            hostname=self._host, port=self._port, use_tls=True, timeout=SMTP_TIMEOUT_SECONDS
        )
        try:
            async with smtp:
                await smtp.login("resend", self._password)
                _, response = await smtp.send_message(
                    message, sender=envelope_from, recipients=rcpt_to
                )
        except aiosmtplib.SMTPResponseException as exc:
            if 400 <= exc.code < 500:
                raise RetryableError(f"smtp temporary failure {exc.code}") from exc
            raise PermanentSendError(f"smtp {exc.code}: {exc.message[:200]}") from exc
        except (aiosmtplib.SMTPException, OSError, TimeoutError) as exc:
            raise RetryableError(f"smtp unavailable ({type(exc).__name__})") from exc
        return response.strip()
