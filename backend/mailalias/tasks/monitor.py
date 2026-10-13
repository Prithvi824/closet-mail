"""Celery task that checks system health every few minutes and emails admins about problems."""

# local imports
from mailalias.integrations.cloudflare_queue import CloudflareQueueAdmin
from mailalias.mail.outbound import get_direct_mailer
from mailalias.services.monitor import collect_alerts, send_alerts
from mailalias.services.system_mail import SystemMailService
from mailalias.tasks.celery_app import TaskContext, celery_app, run_async


@celery_app.task(name="monitor.check")
def check() -> int:
    """Collect alerts and email new ones to the admins.

    Returns:
        Number of alerts emailed.
    """

    async def _run(ctx: TaskContext) -> int:
        """Run the checks.

        Args:
            ctx: Task resources.
        Returns:
            Alerts emailed.
        """
        async with ctx.session_factory() as db:
            alerts = await collect_alerts(
                db, ctx.settings, ctx.redis, CloudflareQueueAdmin(ctx.cf_api)
            )
            mail = SystemMailService(get_direct_mailer(ctx.settings), ctx.settings)
            return await send_alerts(db, ctx.redis, mail, alerts)

    return run_async(_run)
