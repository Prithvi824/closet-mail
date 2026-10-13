"""Command-line entry point (`mailalias ...`) for admin and runtime commands."""

# 1st party imports
import asyncio

# 3rd party imports
import typer

# local imports
from mailalias import __version__
from mailalias.api.errors import DomainError
from mailalias.config import get_settings
from mailalias.db import get_engine, get_redis, get_session_factory
from mailalias.integrations.cloudflare_api import CloudflareApi
from mailalias.integrations.cloudflare_queue import CloudflareQueueInbox
from mailalias.integrations.r2 import R2Storage
from mailalias.integrations.rspamd import RspamdClient
from mailalias.logging_setup import configure_logging
from mailalias.mail.outbound import QueuedMailer, get_direct_mailer
from mailalias.mail.processor import MailProcessor
from mailalias.models import UserRole
from mailalias.services.system_mail import SystemMailService
from mailalias.services.users import UserService

app = typer.Typer(help="Mail alias platform management commands.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Mail alias platform management commands.

    Returns:
        None. Keeps Typer in multi-command mode.
    """


@app.command()
def version() -> None:
    """Print the backend version.

    Returns:
        None. Writes the version string to stdout.
    """
    typer.echo(__version__)


async def _create_admin(username: str, email: str, password: str) -> str:
    """Create an admin account in one transaction.

    Args:
        username: Admin username.
        email: Admin email (becomes a verified recipient).
        password: Plaintext password.
    Returns:
        The created username.
    """
    try:
        async with get_session_factory()() as db:
            user = await UserService(db).create_user(username, email, password, UserRole.ADMIN)
            await db.commit()
            return user.username
    finally:
        await get_engine().dispose()


@app.command("create-admin")
def create_admin(
    username: str = typer.Option(..., help="Admin username"),
    email: str = typer.Option(..., help="Admin email address"),
    password: str = typer.Option(
        ..., prompt=True, confirmation_prompt=True, hide_input=True, help="Password (prompted)"
    ),
) -> None:
    """Create an administrator account.

    Args:
        username: Admin username.
        email: Admin email.
        password: Password, prompted interactively when not given.
    Returns:
        None. Exits with code 1 on validation errors.
    """
    try:
        created = asyncio.run(_create_admin(username, email, password))
    except DomainError as exc:
        typer.echo(f"error: {exc.message}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"admin '{created}' created")


@app.command("send-test-mail")
def send_test_mail(to: str = typer.Option(..., help="Recipient (use an inbox you own)")) -> None:
    """Send one system test email directly through the configured mailer.

    Args:
        to: Recipient address.
    Returns:
        None. Prints the provider message id.
    """
    settings = get_settings()
    mail = SystemMailService(get_direct_mailer(settings), settings)
    provider_id = asyncio.run(
        mail.send(
            "notice",
            to,
            subject="closetcompute.online test message",
            body="This is a test message from the mail-alias backend.",
        )
    )
    typer.echo(f"sent: {provider_id}")


async def _run_processor() -> None:
    """Wire the real queue, R2, mailer and DB into a MailProcessor and run it.

    Returns:
        None. Returns after SIGTERM/SIGINT.
    """
    settings = get_settings()
    api = CloudflareApi(settings)
    storage = R2Storage(settings)
    spam = RspamdClient(settings)
    inbox = CloudflareQueueInbox(api, storage, settings.cf_queue_id_inbound)
    processor = MailProcessor(
        inbox=inbox,
        mailer=get_direct_mailer(settings),
        session_factory=get_session_factory(),
        settings=settings,
        redis=get_redis(),
        system_mail=SystemMailService(QueuedMailer(), settings),
        spam=spam,
        storage=storage,
    )
    try:
        await processor.run_forever()
    finally:
        await spam.aclose()
        await api.aclose()
        await get_redis().aclose()
        await get_engine().dispose()


@app.command()
def processor() -> None:
    """Run the inbound mail processor until SIGTERM/SIGINT.

    Returns:
        None.
    """
    configure_logging("processor")
    asyncio.run(_run_processor())
