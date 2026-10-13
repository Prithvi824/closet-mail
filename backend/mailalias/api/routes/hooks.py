"""Inbound webhooks: Resend delivery events (Svix-signed)."""

# 1st party imports
import json
import logging

# 3rd party imports
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from svix.webhooks import Webhook, WebhookVerificationError

# local imports
from mailalias.api.deps import AppSettings, DbSession, SystemMail
from mailalias.api.errors import error_body
from mailalias.services.failed_deliveries import FailedDeliveryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hooks", tags=["hooks"])


@router.post("/email-events")
async def email_events(
    request: Request, db: DbSession, settings: AppSettings, system_mail: SystemMail
) -> JSONResponse:
    """Verify and record a Resend event; retries of the same event are acknowledged once.

    Args:
        request: Raw request (the signature covers the exact body).
        db, settings, system_mail: Request dependencies.
    Returns:
        200 {"recorded": n}; 400 for a bad signature; 503 when no secret is configured.
    """
    secret = settings.resend_webhook_secret.get_secret_value()
    if not secret:
        return JSONResponse(error_body("not_configured", "Webhook secret not set"), status_code=503)
    body = await request.body()
    try:
        Webhook(secret).verify(body, dict(request.headers))
        event = json.loads(body)
    except (WebhookVerificationError, ValueError):
        return JSONResponse(error_body("bad_signature", "Invalid signature"), status_code=400)
    event_id = request.headers.get("svix-id", "")
    written = await FailedDeliveryService(db, system_mail).record_email_event(event_id, event)
    await db.commit()
    logger.info("email event", extra={"type": event.get("type"), "recorded": written})
    return JSONResponse({"recorded": written})
