"""Celery task that refreshes every subdomain's routing status (DNS, edge flag, inboxes)."""

# 1st party imports
import logging

# local imports
from mailalias.integrations.cloudflare_dns import CloudflareDns
from mailalias.services.subdomain_status import SubdomainStatusChecker
from mailalias.tasks.celery_app import TaskContext, celery_app, run_async

logger = logging.getLogger(__name__)


@celery_app.task(name="subdomains.check_status")
def check_status() -> int:
    """Check every live subdomain; skipped when no Cloudflare zone is configured.

    Returns:
        Number of subdomains checked.
    """

    async def _run(ctx: TaskContext) -> int:
        if not ctx.settings.cf_zone_id:
            logger.info("subdomain status check skipped: CF_ZONE_ID is not set")
            return 0
        async with ctx.session_factory() as db:
            dns = CloudflareDns(ctx.cf_api, ctx.settings.cf_zone_id)
            checked = await SubdomainStatusChecker(db, dns, ctx.kv, ctx.settings).check_all()
            await db.commit()
        logger.info("subdomain status checked", extra={"subdomains": checked})
        return checked

    return run_async(_run)
