"""Remove tracking pixels from HTML bodies."""

# 1st party imports
import re
from email.message import EmailMessage
from functools import lru_cache
from importlib import resources
from urllib.parse import urlsplit

# 3rd party imports
from selectolax.lexbor import LexborHTMLParser

# local imports
from mailalias.mail.transform.context import TransformContext
from mailalias.mail.transform.mime import body_parts, get_text, set_text

SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(px)?\s*$", re.IGNORECASE)
STYLE_HIDDEN_RE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.IGNORECASE)
STYLE_SIZE_RE = re.compile(r"(?:^|;)\s*(?:width|height)\s*:\s*([0-9.]+)\s*px", re.IGNORECASE)


@lru_cache
def tracker_domains() -> frozenset[str]:
    """Known tracking hosts from data/trackers.txt.

    Returns:
        Lowercase domains (subdomains match too).
    """
    text = resources.files("mailalias.data").joinpath("trackers.txt").read_text()
    return frozenset(
        line.strip().lower()
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    )


def _is_tiny(value: str | None) -> bool:
    """Whether a width/height attribute is at most 1 pixel.

    Args:
        value: Attribute value.
    Returns:
        True for "0", "1", "1px" and similar.
    """
    match = SIZE_RE.match(value or "")
    return match is not None and float(match.group(1)) <= 1


def _is_tracker_host(src: str | None) -> bool:
    """Whether an image URL points to a known tracking domain.

    Args:
        src: Image src.
    Returns:
        True when the host or a parent domain is listed.
    """
    host = (urlsplit(src or "").hostname or "").lower()
    domains = tracker_domains()
    labels = host.split(".")
    return any(".".join(labels[i:]) in domains for i in range(len(labels) - 1))


def is_tracking_image(attributes: dict[str, str | None]) -> bool:
    """Classify an <img> by size, visibility and host.

    Args:
        attributes: The tag's attributes.
    Returns:
        True when the image looks like a tracking pixel.
    """
    style = attributes.get("style") or ""
    tiny_style = any(float(size) <= 1 for size in STYLE_SIZE_RE.findall(style))
    return (
        _is_tiny(attributes.get("width"))
        or _is_tiny(attributes.get("height"))
        or tiny_style
        or bool(STYLE_HIDDEN_RE.search(style))
        or _is_tracker_host(attributes.get("src"))
    )


def strip_trackers(msg: EmailMessage, ctx: TransformContext) -> EmailMessage:
    """Remove tracking images from the HTML body (only re-serialised if something changed).

    Args:
        msg: Message being built (modified in place).
        ctx: Transform context (no-op unless strip_trackers is on).
    Returns:
        The same message.
    """
    part = body_parts(msg).get("html")
    if not ctx.strip_trackers or part is None:
        return msg
    tree = LexborHTMLParser(get_text(part))
    trackers = [node for node in tree.css("img") if is_tracking_image(node.attributes)]
    if trackers:
        for node in trackers:
            node.decompose()
        set_text(part, tree.html or "", is_root=part is msg)
    return msg
