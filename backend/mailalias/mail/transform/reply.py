"""build_reply: turn the owner's reply into mail sent from the alias, with no trace of the owner."""

# 1st party imports
import copy
import re
from email.headerregistry import Address
from email.message import EmailMessage

# 3rd party imports
from selectolax.lexbor import LexborHTMLParser

# local imports
from mailalias.mail.transform.banner import HTML_END, HTML_START, TEXT_END, TEXT_START
from mailalias.mail.transform.context import ReplyContext
from mailalias.mail.transform.forward import repackage_pgp_mime, with_text_body
from mailalias.mail.transform.mime import get_text, set_text, text_bodies

STRIPPED_HEADERS = (
    "Received",
    "X-Received",
    "DKIM-Signature",
    "Authentication-Results",
    "Received-SPF",
    "Return-Path",
    "Sender",
    "X-Originating-IP",
    "Reply-To",
    "Message-ID",
    "Bcc",
    "Delivered-To",
    "Disposition-Notification-To",
    "Return-Receipt-To",
    "X-Confirm-Reading-To",
)
STRIPPED_PREFIXES = ("arc-", "x-gm-", "x-google-", "x-original-", "x-cf-", "x-closet-")
MSG_ID_RE = re.compile(r"<[^<>\s]+>")
PROVIDER_ID_SUFFIX = ".amazonses.com>"
TEXT_BANNER_RE = re.compile(
    rf"^[>\s]*{re.escape(TEXT_START)}[ \t]*$.*?^[>\s]*{re.escape(TEXT_END)}[ \t]*(?:\r?\n|$)",
    re.MULTILINE | re.DOTALL,
)
HTML_BANNER_RE = re.compile(rf"{re.escape(HTML_START)}.*?{re.escape(HTML_END)}", re.DOTALL)
# Clients that rebuild text/plain from the quoted HTML keep the banner wording but no markers.
RENDERED_BANNER_RE = (
    r"^[>\s]*Sent to \*?{alias}\*? from .{{0,600}}?Disable alias[^\n]*(?:\n|$)"
    r"(?:[>\s]*The sender asked replies to go to:[^\n]*(?:\n|$))?"
)
# An address must not match inside a longer one ("a@x.com" in "aa@x.com" or "a@x.com.au").
ADDRESS_LEFT, ADDRESS_RIGHT = r"(?<![\w.%+-])", r"(?![\w-]|\.\w)"


def _replace_all(text: str, mapping: dict[str, str]) -> str:
    """Case-insensitively replace whole addresses in one pass (replacements are not re-scanned).

    Args:
        text: Input.
        mapping: Lowercase address -> replacement.
    Returns:
        The rewritten text.
    """
    needles = sorted((needle for needle in mapping if needle), key=len, reverse=True)
    if not needles:
        return text
    pattern = ADDRESS_LEFT + "(" + "|".join(map(re.escape, needles)) + ")" + ADDRESS_RIGHT
    return re.sub(pattern, lambda m: mapping[m.group(1).lower()], text, flags=re.IGNORECASE)


def _clean_text(text: str, ctx: ReplyContext, mapping: dict[str, str]) -> str:
    """Remove quoted banners and action links, then rewrite addresses in a text body.

    Args:
        text: Plain-text body.
        ctx: Reply context.
        mapping: Address rewrites (tokens -> real, owner -> alias).
    Returns:
        Clean text.
    """
    text = TEXT_BANNER_RE.sub("", text)
    rendered = RENDERED_BANNER_RE.format(alias=re.escape(ctx.alias_address))
    text = re.sub(rendered, "", text, flags=re.MULTILINE | re.DOTALL | re.IGNORECASE)
    lines = [line for line in text.splitlines(keepends=True) if ctx.action_url_prefix not in line]
    return _replace_all("".join(lines), mapping)


def _clean_html(document: str, ctx: ReplyContext, mapping: dict[str, str]) -> str:
    """Remove quoted banners (marker comments may be gone after quoting) and rewrite addresses.

    Args:
        document: HTML body.
        ctx: Reply context.
        mapping: Address rewrites.
    Returns:
        Clean HTML.
    """
    document = HTML_BANNER_RE.sub("", document)
    if ctx.action_url_prefix in document:
        tree = LexborHTMLParser(document)
        for link in tree.css("a"):
            if (link.attributes.get("href") or "").startswith(ctx.action_url_prefix):
                container = link.parent
                (
                    container if container is not None and container.tag != "body" else link
                ).decompose()
        document = tree.html or ""
    return _replace_all(document, mapping)


def _fix_threading(msg: EmailMessage) -> None:
    """Drop relay-assigned ids from References/In-Reply-To; point In-Reply-To at the original.

    Args:
        msg: Message, modified in place.
    Returns:
        None.
    """
    references = [
        mid
        for mid in MSG_ID_RE.findall(str(msg.get("References", "")))
        if not mid.lower().endswith(PROVIDER_ID_SUFFIX)
    ]
    in_reply_to = [
        mid
        for mid in MSG_ID_RE.findall(str(msg.get("In-Reply-To", "")))
        if not mid.lower().endswith(PROVIDER_ID_SUFFIX)
    ]
    del msg["References"]
    del msg["In-Reply-To"]
    if references:
        msg["References"] = " ".join(references)
    if in_reply_to or references:
        msg["In-Reply-To"] = (in_reply_to or references)[-1]


def _address_list(entries: tuple[tuple[str, str], ...]) -> list[Address]:
    """Header Address objects from (display name, address) pairs.

    Args:
        entries: Pairs.
    Returns:
        Addresses.
    """
    return [Address(display_name=name, addr_spec=address) for name, address in entries]


def _scrub_headers(msg: EmailMessage, owner_map: dict[str, str]) -> None:
    """Rewrite any remaining header value that still mentions an owner address.

    Args:
        msg: Message, modified in place.
        owner_map: Owner address -> alias.
    Returns:
        None.
    """
    for name in {
        key for key, value in msg.items() if any(owner in str(value).lower() for owner in owner_map)
    }:
        values = [_replace_all(str(value), owner_map) for value in msg.get_all(name, [])]
        del msg[name]
        for value in values:
            msg[name] = value


def build_reply(original: EmailMessage, ctx: ReplyContext) -> EmailMessage:
    """Build the outgoing reply: From the alias, real recipients, owner traces removed.

    Args:
        original: The owner's message as received on the reply domain (never modified).
        ctx: Addresses and mappings prepared by the handler.
    Returns:
        A new EmailMessage ready for the outbound mailer.
    """
    msg = with_text_body(repackage_pgp_mime(copy.deepcopy(original)))
    for name in STRIPPED_HEADERS:
        del msg[name]
    for name in {key for key in msg if key.lower().startswith(STRIPPED_PREFIXES)}:
        del msg[name]
    _fix_threading(msg)
    for name in ("From", "To", "Cc"):
        del msg[name]
    msg["From"] = Address(addr_spec=ctx.alias_address)
    if ctx.to:
        msg["To"] = _address_list(ctx.to)
    if ctx.cc:
        msg["Cc"] = _address_list(ctx.cc)

    owner_map = {owner.lower(): ctx.alias_address for owner in ctx.owner_addresses}
    mapping = {**{t.lower(): real for t, real in ctx.token_addresses.items()}, **owner_map}
    for part in text_bodies(msg):
        text = get_text(part)
        if part.get_content_subtype() == "html":
            cleaned = _clean_html(text, ctx, mapping)
        else:
            cleaned = _clean_text(text, ctx, mapping)
        if cleaned != text:
            set_text(part, cleaned, is_root=part is msg)
    _scrub_headers(msg, owner_map)
    return msg
