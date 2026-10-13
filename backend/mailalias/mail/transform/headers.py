"""Forward-mode header rewriting: hide the sender behind the reply token, drop transport traces."""

# 1st party imports
import re
from email.headerregistry import Address
from email.message import EmailMessage

# local imports
from mailalias.mail.transform.context import TransformContext

# Exact header names removed from forwarded mail (transport traces, auth results, and headers
# that would make the owner's client contact the sender directly, e.g. read receipts).
STRIPPED_HEADERS = (
    "DKIM-Signature",
    "Authentication-Results",
    "Received-SPF",
    "Return-Path",
    "Received",
    "Sender",
    "Delivered-To",
    "Bcc",
    "Disposition-Notification-To",
    "Return-Receipt-To",
    "X-Confirm-Reading-To",
)
STRIPPED_PREFIXES = ("arc-", "x-original-", "x-cf-", "x-closet-")
LIST_UNSUBSCRIBE_ENTRY = re.compile(r"<([^>]*)>")
ALIAS_HEADER = "X-Closet-Alias"
NOTICE_HEADER = "X-Closet-Notice"


def strip_transport_headers(msg: EmailMessage) -> EmailMessage:
    """Remove trace, authentication and receipt headers (and any spoofed X-Closet-*).

    Runs first, so later steps may add their own X-Closet-* headers.

    Args:
        msg: Message, modified in place.
    Returns:
        The same message.
    """
    for name in STRIPPED_HEADERS:
        del msg[name]
    for name in {key for key in msg if key.lower().startswith(STRIPPED_PREFIXES)}:
        del msg[name]
    return msg


def _thread_references(msg: EmailMessage, message_id: str | None) -> None:
    """Append the original Message-ID to References (the relay replaces Message-ID).

    Args:
        msg: Message, modified in place.
        message_id: Original Message-ID value, if any.
    Returns:
        None.
    """
    if not message_id:
        return
    message_id = message_id.strip()
    references = " ".join(str(msg.get("References", "")).split())
    if message_id not in references.split():
        del msg["References"]
        msg["References"] = f"{references} {message_id}".strip()


def _rewrite_list_unsubscribe(msg: EmailMessage) -> None:
    """Keep only https: unsubscribe links; mailto: would reveal the owner's real address.

    Args:
        msg: Message, modified in place.
    Returns:
        None.
    """
    value = msg.get("List-Unsubscribe")
    if value is None:
        return
    kept = [url for url in LIST_UNSUBSCRIBE_ENTRY.findall(str(value)) if url.startswith("https:")]
    del msg["List-Unsubscribe"]
    if kept:
        msg["List-Unsubscribe"] = ", ".join(f"<{url}>" for url in kept)
    else:
        del msg["List-Unsubscribe-Post"]


def rewrite_forward_headers(msg: EmailMessage, ctx: TransformContext) -> EmailMessage:
    """Set the token From/Reply-To, thread via References and tag the alias (runs last).

    Args:
        msg: Message being built (modified in place).
        ctx: Transform context.
    Returns:
        The same message.
    """
    message_id = msg.get("Message-ID")
    del msg["Message-ID"]
    _thread_references(msg, str(message_id) if message_id else None)
    _rewrite_list_unsubscribe(msg)
    token_local, _, token_domain = ctx.contact_token_address.partition("@")
    sender = Address(display_name=ctx.sender_display, username=token_local, domain=token_domain)
    for name in ("From", "Reply-To"):
        del msg[name]
        msg[name] = sender
    msg[ALIAS_HEADER] = ctx.alias_address
    return msg
