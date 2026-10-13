"""System emails (invites, verification, password reset, notices) built from templates."""

# 1st party imports
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from string import Template

# local imports
from mailalias.config import Settings
from mailalias.mail.outbound import OutboundMailer

_FOOTER = "\n--\nclosetcompute.online mail aliases\n"

_TEMPLATES: dict[str, tuple[str, Template]] = {
    "invite": (
        "You're invited to closetcompute.online mail aliases",
        Template(
            "You have been invited to create an account.\n\n"
            "Accept the invite (valid for 7 days):\n$link\n"
        ),
    ),
    "verify_recipient": (
        "Confirm your forwarding address",
        Template(
            "Someone (hopefully you) added this address as a forwarding destination.\n\n"
            "Confirm it (valid for 48 hours):\n$link\n\n"
            "If this wasn't you, ignore this email.\n"
        ),
    ),
    "password_reset": (
        "Reset your password",
        Template(
            "A password reset was requested for your account.\n\n"
            "Choose a new password (valid for 1 hour):\n$link\n\n"
            "If this wasn't you, ignore this email; your password is unchanged.\n"
        ),
    ),
    "notice": ("$subject", Template("$body\n")),
}


class SystemMailService:
    """Builds and sends mail from SYSTEM_FROM."""

    def __init__(self, mailer: OutboundMailer, settings: Settings) -> None:
        """Build the service.

        Args:
            mailer: Outbound mailer (direct, queued, or fake).
            settings: Provides SYSTEM_FROM and APP_BASE_URL.
        Returns:
            None.
        """
        self._mailer = mailer
        self._settings = settings

    def link(self, path: str) -> str:
        """Absolute dashboard URL.

        Args:
            path: Path starting with "/".
        Returns:
            APP_BASE_URL + path.
        """
        return self._settings.app_base_url.rstrip("/") + path

    def build(self, template: str, to: str, **values: str) -> EmailMessage:
        """Render a template into a plain-text message.

        Args:
            template: Template name (invite, verify_recipient, password_reset, notice).
            to: Recipient address.
            values: Template variables (link, subject, body).
        Returns:
            The message ready to send.
        """
        subject, body = _TEMPLATES[template]
        message = EmailMessage()
        message["From"] = f"closetcompute.online <{self._settings.system_from}>"
        message["To"] = to
        message["Subject"] = Template(subject).safe_substitute(values)
        message["Date"] = formatdate(localtime=False)
        message["Message-ID"] = make_msgid(domain=self._settings.alias_domain)
        message["Auto-Submitted"] = "auto-generated"
        message.set_content(body.safe_substitute(values) + _FOOTER)
        return message

    async def send(self, template: str, to: str, **values: str) -> str:
        """Render and send a system email.

        Args:
            template: Template name.
            to: Recipient address.
            values: Template variables.
        Returns:
            The provider message id.
        """
        message = self.build(template, to, **values)
        return await self._mailer.send(message, self._settings.system_from, [to])
