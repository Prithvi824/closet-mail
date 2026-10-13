"""Celery tasks that send mail (system mail queued by the API)."""

# 1st party imports
import base64
import logging
from email import message_from_bytes, policy
from email.message import EmailMessage
from typing import Any

# local imports
from mailalias.mail.outbound import PermanentSendError, get_direct_mailer
from mailalias.mail.types import RetryableError
from mailalias.services.quota import QuotaService
from mailalias.tasks.celery_app import TaskContext, celery_app, run_async

logger = logging.getLogger(__name__)

SEND_RETRIES = 3
CAP_RETRY_SECONDS = 3600
CAP_MAX_WAITS = 30  # hourly checks: covers the rest of the UTC day plus slack


class SendCapReached(Exception):
    """Today's provider cap is used up."""


@celery_app.task(name="mail.send_system_mail", bind=True, max_retries=None)
def send_system_mail(self: Any, raw_b64: str, envelope_from: str, rcpt_to: list[str]) -> str | None:
    """Send a system email, respecting the global daily cap.

    Args:
        self: Bound Celery task (for retries).
        raw_b64: Base64 of the full MIME message.
        envelope_from: SMTP MAIL FROM.
        rcpt_to: Recipients.
    Returns:
        The provider message id, or None if permanently rejected or out of retries.
    """
    message = message_from_bytes(base64.b64decode(raw_b64), policy=policy.default)
    assert isinstance(message, EmailMessage)

    async def _run(ctx: TaskContext) -> str | None:
        quota = QuotaService(ctx.redis, ctx.settings)
        if not await quota.global_send_allowed():
            raise SendCapReached
        try:
            return await get_direct_mailer(ctx.settings).send(message, envelope_from, rcpt_to)
        except RetryableError:
            await quota.refund_global()
            raise
        except PermanentSendError:
            logger.error("system mail rejected permanently", extra={"rcpt_count": len(rcpt_to)})
            return None

    try:
        return run_async(_run)
    except SendCapReached as exc:
        if self.request.retries >= CAP_MAX_WAITS:
            logger.error("system mail dropped: send cap reached all day")
            return None
        raise self.retry(exc=exc, countdown=CAP_RETRY_SECONDS) from exc
    except RetryableError as exc:
        if self.request.retries >= SEND_RETRIES:
            logger.error("system mail dropped after retries", extra={"error": str(exc)})
            return None
        raise self.retry(exc=exc, countdown=30 * 2**self.request.retries) from exc
