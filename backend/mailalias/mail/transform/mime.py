"""MIME helpers shared by transform steps: find body parts and rewrite their text safely."""

# 1st party imports
from collections.abc import Iterator
from email.message import EmailMessage

TEXT_SUBTYPES = ("plain", "html")
# Headers that EmailMessage.set_content drops but that must survive a body rewrite.
PRESERVED_PART_HEADERS = ("Content-ID", "Content-Disposition", "Content-Location")


def iter_leaves(part: EmailMessage) -> Iterator[EmailMessage]:
    """Leaf parts in document order, without descending into attached messages.

    Args:
        part: Message or multipart part.
    Returns:
        Iterator of non-multipart parts (message/rfc822 parts are yielded, not entered).
    """
    if part.is_multipart() and part.get_content_maintype() == "multipart":
        for child in part.iter_parts():
            yield from iter_leaves(child)  # type: ignore[arg-type]
    else:
        yield part


def body_parts(msg: EmailMessage) -> dict[str, EmailMessage]:
    """The first inline text/plain and text/html body parts.

    Args:
        msg: Message.
    Returns:
        Mapping "plain"/"html" -> part, for the subtypes that exist.
    """
    found: dict[str, EmailMessage] = {}
    for part in iter_leaves(msg):
        subtype = part.get_content_subtype()
        if (
            part.get_content_maintype() == "text"
            and subtype in TEXT_SUBTYPES
            and subtype not in found
            and part.get_content_disposition() != "attachment"
        ):
            found[subtype] = part
    return found


def text_bodies(msg: EmailMessage) -> list[EmailMessage]:
    """Every inline text/plain and text/html leaf (attachments and attached messages excluded).

    Args:
        msg: Message.
    Returns:
        The parts in document order.
    """
    return [
        part
        for part in iter_leaves(msg)
        if part.get_content_maintype() == "text"
        and part.get_content_subtype() in TEXT_SUBTYPES
        and part.get_content_disposition() != "attachment"
    ]


def get_text(part: EmailMessage) -> str:
    """Decoded text of a text part, tolerating bad charsets.

    Args:
        part: text/* part.
    Returns:
        The content as str.
    """
    try:
        return str(part.get_content())
    except (LookupError, UnicodeDecodeError):
        payload = part.get_payload(decode=True)
        return payload.decode("utf-8", "replace") if isinstance(payload, bytes) else ""


def set_text(part: EmailMessage, text: str, *, is_root: bool) -> None:
    """Replace a text part's content, keeping its charset when it can encode the text.

    Args:
        part: text/plain or text/html part.
        text: New content.
        is_root: Whether the part is the message itself (keeps MIME-Version there).
    Returns:
        None.
    """
    preserved = [(name, part[name]) for name in PRESERVED_PART_HEADERS if part[name] is not None]
    charset = part.get_content_charset() or "utf-8"
    subtype = part.get_content_subtype()
    try:
        text.encode(charset)
    except (LookupError, UnicodeEncodeError):
        charset = "utf-8"
    part.set_content(text, subtype=subtype, charset=charset)
    for name, value in preserved:
        del part[name]
        part[name] = value
    if not is_root:
        del part["MIME-Version"]


def content_free_copy(msg: EmailMessage) -> EmailMessage:
    """A new message carrying msg's non-content headers.

    Args:
        msg: Source message.
    Returns:
        EmailMessage without Content-* or MIME-Version headers and without a body.
    """
    shell = EmailMessage()
    for name, value in msg.items():
        if not name.lower().startswith("content-") and name.lower() != "mime-version":
            shell[name] = value
    return shell
