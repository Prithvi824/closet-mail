"""Decide which handler an inbound message goes to, from its envelope recipient."""

# 1st party imports
from email.message import EmailMessage

# local imports
from mailalias.config import Settings
from mailalias.mail.addresses import split_address
from mailalias.mail.dsn import is_dsn
from mailalias.mail.types import InboundEnvelope, MailKind


def classify(env: InboundEnvelope, msg: EmailMessage, settings: Settings) -> MailKind:
    """Route a message by recipient domain.

    Args:
        env: Queue envelope (rcpt_to and mail_from are used).
        msg: Parsed message (used for DSN detection on the reply domain).
        settings: Domains configuration.
    Returns:
        BOUNCE/REPLY on the reply domain, FORWARD on the alias domain or a one-label
        personal subdomain of it, DROP otherwise.
    """
    try:
        _, domain = split_address(env.rcpt_to)
    except ValueError:
        return MailKind.DROP
    alias_domain = settings.alias_domain.lower()
    if domain == settings.reply_domain.lower():
        return MailKind.BOUNCE if is_dsn(msg, env.mail_from) else MailKind.REPLY
    if domain == alias_domain:
        return MailKind.FORWARD
    label = domain.removesuffix("." + alias_domain)
    if label != domain and label and "." not in label:
        return MailKind.FORWARD
    return MailKind.DROP
