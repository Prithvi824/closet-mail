"""build_forward: turn an inbound message into the copy delivered to the alias owner."""

# 1st party imports
import copy
from email.message import EmailMessage
from typing import cast

# local imports
from mailalias.mail.transform.banner import add_banner
from mailalias.mail.transform.context import TransformContext
from mailalias.mail.transform.headers import (
    NOTICE_HEADER,
    rewrite_forward_headers,
    strip_transport_headers,
)
from mailalias.mail.transform.mime import body_parts, content_free_copy
from mailalias.mail.transform.pgp import encrypt_for_recipient, is_encrypted
from mailalias.mail.transform.trackers import strip_trackers

ENCRYPTED_NOTICE = (
    "This message was PGP/MIME encrypted by the sender. Our mail relay cannot carry that "
    "format, so the encrypted content is attached as encrypted.asc; open it with your PGP "
    "software.\n"
)
NO_BODY_NOTICE = "(This message has no text body; see the attachments.)\n"


def repackage_pgp_mime(msg: EmailMessage) -> EmailMessage:
    """Turn multipart/encrypted into a notice plus an encrypted.asc attachment.

    Args:
        msg: Message being built.
    Returns:
        msg unchanged, or a new multipart/mixed message.
    """
    if msg.get_content_type() != "multipart/encrypted":
        return msg
    parts = list(msg.iter_parts())
    payload = parts[-1].get_payload(decode=True) if parts else None
    shell = content_free_copy(msg)
    shell.set_content(ENCRYPTED_NOTICE)
    shell.add_attachment(
        payload if isinstance(payload, bytes) else b"",
        maintype="application",
        subtype="octet-stream",
        filename="encrypted.asc",
    )
    shell[NOTICE_HEADER] = "pgp-mime-repackaged"
    return shell


def with_text_body(msg: EmailMessage) -> EmailMessage:
    """Give body-less messages a text part (the relay rejects mail without text or HTML).

    Args:
        msg: Message being built.
    Returns:
        msg unchanged, or a multipart/mixed copy with a leading text part.
    """
    if body_parts(msg):
        return msg
    shell = content_free_copy(msg)
    shell.set_content(NO_BODY_NOTICE)
    shell.make_mixed()
    if msg.get_content_maintype() == "multipart":
        for part in msg.iter_parts():
            shell.attach(cast(EmailMessage, part))
    else:
        original = copy.deepcopy(msg)
        for name in list(original.keys()):
            if not name.lower().startswith("content-"):
                del original[name]
        shell.attach(original)
    return shell


def repackage_encrypted(msg: EmailMessage, ctx: TransformContext) -> EmailMessage:
    """Transformer step wrapper for repackage_pgp_mime.

    Args:
        msg: Message being built.
        ctx: Transform context (unused).
    Returns:
        The possibly repackaged message.
    """
    return repackage_pgp_mime(msg)


def ensure_text_body(msg: EmailMessage, ctx: TransformContext) -> EmailMessage:
    """Transformer step wrapper for with_text_body.

    Args:
        msg: Message being built.
        ctx: Transform context (unused).
    Returns:
        The message with a text body.
    """
    return with_text_body(msg)


def build_forward(original: EmailMessage, ctx: TransformContext) -> EmailMessage:
    """Build the forwarded copy: sanitise, repackage, strip trackers, banner, PGP, headers.

    Args:
        original: Parsed inbound message (never modified).
        ctx: Per-delivery context.
    Returns:
        A new EmailMessage ready for the outbound mailer.
    """
    msg = strip_transport_headers(copy.deepcopy(original))
    # Decide before the banner is added: a top banner hides inline armor from is_encrypted.
    already_encrypted = is_encrypted(original)
    steps = (
        repackage_encrypted,
        ensure_text_body,
        strip_trackers,
        add_banner,
        *(() if already_encrypted else (encrypt_for_recipient,)),
    )
    for step in steps:
        msg = step(msg, ctx)
    return rewrite_forward_headers(msg, ctx)
