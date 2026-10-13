"""Inline PGP for forwards: the relay rejects PGP/MIME (T4), so every part is armored separately.

Output: multipart/mixed with an armored text/plain body (banner included) and each other part
(the HTML rendition, attachments) encrypted as a `.pgp` attachment. No plaintext content remains.
"""

# 1st party imports
import re
from email.message import EmailMessage
from typing import cast

# 3rd party imports
from selectolax.lexbor import LexborHTMLParser

# local imports
from mailalias.integrations import gpg
from mailalias.mail.transform.context import TransformContext
from mailalias.mail.transform.mime import content_free_copy, get_text, iter_leaves

PGP_ARMOR = "-----BEGIN PGP MESSAGE-----"
PROTECTED_SUBJECT = "..."
HTML_FILENAME = "message.html.pgp"
BLOCK_SELECTOR = "p, div, br, tr, li, h1, h2, h3, h4, h5, h6, blockquote, pre, table, hr"
SPACES_RE = re.compile(r"[ \t\xa0]+")
BLANK_LINES_RE = re.compile(r"\n{3,}")


def _body(msg: EmailMessage, preference: tuple[str, ...]) -> EmailMessage | None:
    """Typed wrapper around EmailMessage.get_body.

    Args:
        msg: Message.
        preference: Subtypes in order of preference.
    Returns:
        The body part, or None.
    """
    return cast(EmailMessage | None, msg.get_body(preference))


def is_encrypted(msg: EmailMessage) -> bool:
    """Whether the content is already PGP-encrypted (PGP/MIME, repackaged, or inline armor).

    Args:
        msg: Message being built.
    Returns:
        True if encrypting again would be pointless.
    """
    if msg.get_content_type() == "multipart/encrypted" or msg.get("X-Closet-Notice") == (
        "pgp-mime-repackaged"
    ):
        return True
    body = _body(msg, ("plain", "html"))
    return body is not None and get_text(body).lstrip().startswith(PGP_ARMOR)


def _plain_text(msg: EmailMessage) -> str:
    """The text rendition: the text/plain body, else text extracted from the HTML.

    Args:
        msg: Message being built.
    Returns:
        Text (may be empty).
    """
    plain = _body(msg, ("plain",))
    if plain is not None:
        return get_text(plain)
    html = _body(msg, ("html",))
    if html is None:
        return ""
    return html_to_text(get_text(html))


def html_to_text(document: str) -> str:
    """Readable text from HTML: line breaks after block elements, inline text kept together.

    Args:
        document: HTML.
    Returns:
        Text ending with a newline, or "" when there is no body.
    """
    tree = LexborHTMLParser(document)
    if tree.body is None:
        return ""
    for node in tree.css("head, script, style"):
        node.decompose()
    for node in tree.css("td, th"):
        node.insert_after(" ")
    for node in tree.css(BLOCK_SELECTOR):
        node.insert_after("\n")
    text = tree.body.text(separator="", strip=False)
    lines = [SPACES_RE.sub(" ", line).strip() for line in text.splitlines()]
    return BLANK_LINES_RE.sub("\n\n", "\n".join(lines)).strip() + "\n"


def _attachment(part: EmailMessage, index: int) -> tuple[str, bytes]:
    """Name and bytes of one attachment (attached messages are serialised as .eml).

    Args:
        part: Attachment part.
        index: 1-based position, for unnamed parts.
    Returns:
        (filename, content bytes).
    """
    if part.get_content_type() == "message/rfc822":
        inner = part.get_payload(0)
        data = inner.as_bytes() if isinstance(inner, EmailMessage) else b""
        return part.get_filename() or f"message-{index}.eml", data
    content = part.get_payload(decode=True)
    return part.get_filename() or f"attachment-{index}", content if isinstance(
        content, bytes
    ) else b""


def encrypt_inline(msg: EmailMessage, armored_key: str, protect_subject: bool) -> EmailMessage:
    """Replace every content part with its PGP-encrypted, armored form.

    Args:
        msg: Message being built (banner already added).
        armored_key: Recipient's public key.
        protect_subject: Move the Subject inside the encrypted text and show "..." outside.
    Returns:
        A new multipart/mixed message, or msg unchanged if it is already encrypted.
    """
    if is_encrypted(msg):
        return msg
    subject = str(msg.get("Subject", ""))
    text = _plain_text(msg)
    if protect_subject and subject:
        text = f"Subject: {subject}\n\n{text}"
    plain, html = _body(msg, ("plain",)), _body(msg, ("html",))
    # Every other leaf (attachments, inline images, extra text parts) is encrypted as a file.
    others = [leaf for leaf in iter_leaves(msg) if leaf is not plain and leaf is not html]
    attachments = [_attachment(part, index) for index, part in enumerate(others, 1)]
    plaintexts = [text.encode()]
    if html is not None:
        plaintexts.append(get_text(html).encode())
    plaintexts += [data for _, data in attachments]
    encrypted = gpg.encrypt_many(plaintexts, armored_key)

    shell = content_free_copy(msg)
    shell.set_content(encrypted[0].decode("ascii"), cte="7bit")
    shell.make_mixed()
    files = ([HTML_FILENAME] if html is not None else []) + [f"{n}.pgp" for n, _ in attachments]
    for filename, data in zip(files, encrypted[1:], strict=True):
        shell.add_attachment(
            data, maintype="application", subtype="pgp-encrypted", filename=filename
        )
    if protect_subject and subject:
        shell.replace_header("Subject", PROTECTED_SUBJECT)
    return shell


def encrypt_for_recipient(msg: EmailMessage, ctx: TransformContext) -> EmailMessage:
    """Transformer step: encrypt when the recipient has a PGP key.

    Args:
        msg: Message being built.
        ctx: Transform context (pgp_public_key, pgp_protect_subject).
    Returns:
        The encrypted message, or msg unchanged.
    """
    if not ctx.pgp_public_key:
        return msg
    return encrypt_inline(msg, ctx.pgp_public_key, ctx.pgp_protect_subject)
