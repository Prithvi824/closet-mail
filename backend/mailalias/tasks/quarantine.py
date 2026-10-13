"""Celery task that delivers a message released from quarantine."""

# 1st party imports
import uuid

# local imports
from mailalias.integrations.r2 import R2Storage
from mailalias.mail.handlers.forward import ForwardHandler
from mailalias.mail.outbound import QueuedMailer, get_direct_mailer
from mailalias.mail.processor import parse_message
from mailalias.mail.types import HandlerResult, InboundEnvelope
from mailalias.services.quarantine import RELEASE_TASK, QuarantineService
from mailalias.services.system_mail import SystemMailService
from mailalias.tasks.celery_app import TaskContext, celery_app, run_async
from mailalias.tasks.kv import RETRY_OPTIONS


@celery_app.task(name=RELEASE_TASK, **RETRY_OPTIONS)
def release(item_id: str) -> str | None:
    """Forward a released message to the owner, skipping the spam check.

    Args:
        item_id: Quarantine item id.
    Returns:
        The forward outcome, or None if there was nothing to release.
    """

    async def _run(ctx: TaskContext) -> str | None:
        storage = R2Storage(ctx.settings)
        async with ctx.session_factory() as db:
            handler = ForwardHandler(
                db,
                ctx.settings,
                get_direct_mailer(ctx.settings),
                ctx.redis,
                SystemMailService(QueuedMailer(), ctx.settings),
                storage=storage,
            )

            async def forward(env: InboundEnvelope, raw: bytes) -> HandlerResult:
                """Run the forward path without the spam screen.

                Args:
                    env, raw: Synthetic envelope and the decrypted message.
                Returns:
                    The handler result.
                """
                return await handler.handle(env, parse_message(raw), raw, skip_spam=True)

            service = QuarantineService(db, ctx.settings, storage)
            result = await service.release(uuid.UUID(item_id), forward)
            await db.commit()
        return result.outcome.value if result else None

    return run_async(_run)
