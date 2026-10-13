"""Forward-mode banner: who sent this, to which alias, and one-click block/disable links."""

# 1st party imports
import html
import re
from email.message import EmailMessage
from email.utils import getaddresses

# local imports
from mailalias.mail.transform.context import TransformContext
from mailalias.mail.transform.mime import body_parts, get_text, set_text

HTML_START, HTML_END = "<!--closet-banner:start-->", "<!--closet-banner:end-->"
TEXT_START, TEXT_END = "-- closet-banner --", "-- end closet-banner --"
BODY_OPEN = re.compile(r"<body\b[^>]*>", re.IGNORECASE)
BODY_CLOSE = re.compile(r"</body\s*>", re.IGNORECASE)
HTML_STYLE = (
    "margin:0 0 12px 0;padding:8px 12px;border:1px solid #d0d7de;border-radius:6px;"
    "background:#f6f8fa;color:#24292f;font:13px/1.5 -apple-system,Segoe UI,Arial,sans-serif;"
)


def differing_reply_to(msg: EmailMessage) -> str | None:
    """The sender-set Reply-To address when it differs from From.

    Args:
        msg: Original message (before header rewriting).
    Returns:
        The Reply-To address, or None.
    """
    reply_to = [addr.lower() for _, addr in getaddresses([str(msg.get("Reply-To", ""))]) if addr]
    senders = {addr.lower() for _, addr in getaddresses([str(msg.get("From", ""))]) if addr}
    differing = [addr for addr in reply_to if addr not in senders]
    return ", ".join(differing) or None


def text_banner(ctx: TransformContext, reply_to: str | None) -> str:
    """Plain-text banner block.

    Args:
        ctx: Transform context.
        reply_to: Differing Reply-To to disclose, if any.
    Returns:
        The banner including its marker lines.
    """
    lines = [
        TEXT_START,
        f"Sent to {ctx.alias_address} from {ctx.sender_display}",
        f"Block sender: {ctx.banner.block_sender_url}",
        f"Disable alias: {ctx.banner.disable_alias_url}",
    ]
    if reply_to:
        lines.append(f"The sender asked replies to go to: {reply_to}")
    return "\n".join([*lines, TEXT_END])


def html_banner(ctx: TransformContext, reply_to: str | None) -> str:
    """HTML banner block (inline styles only, escaped values).

    Args:
        ctx: Transform context.
        reply_to: Differing Reply-To to disclose, if any.
    Returns:
        The banner wrapped in its comment markers.
    """
    esc = html.escape
    extra = f"<br>The sender asked replies to go to: {esc(reply_to)}" if reply_to else ""
    return (
        f'{HTML_START}<div style="{HTML_STYLE}">Sent to <b>{esc(ctx.alias_address)}</b> from '
        f"{esc(ctx.sender_display)} &middot; "
        f'<a href="{esc(ctx.banner.block_sender_url)}">Block sender</a> &middot; '
        f'<a href="{esc(ctx.banner.disable_alias_url)}">Disable alias</a>{extra}</div>{HTML_END}'
    )


def _insert_html(document: str, banner: str, top: bool) -> str:
    """Place the banner right after <body> (top) or before </body> (bottom).

    Args:
        document: HTML text.
        banner: Banner HTML.
        top: Position.
    Returns:
        The new HTML.
    """
    if top:
        match = BODY_OPEN.search(document)
        return (
            document[: match.end()] + banner + document[match.end() :]
            if match
            else banner + document
        )
    closes = list(BODY_CLOSE.finditer(document))
    if not closes:
        return document + banner
    index = closes[-1].start()
    return document[:index] + banner + document[index:]


def add_banner(msg: EmailMessage, ctx: TransformContext) -> EmailMessage:
    """Add the banner to the first text and HTML body parts (skipped when position is off).

    Args:
        msg: Message being built (modified in place; From/Reply-To not yet rewritten).
        ctx: Transform context.
    Returns:
        The same message.
    """
    if ctx.banner.position == "off":
        return msg
    top = ctx.banner.position == "top"
    reply_to = differing_reply_to(msg)
    parts = body_parts(msg)
    if "plain" in parts:
        part, banner = parts["plain"], text_banner(ctx, reply_to)
        body = get_text(part)
        set_text(
            part, f"{banner}\n\n{body}" if top else f"{body}\n\n{banner}\n", is_root=part is msg
        )
    if "html" in parts:
        part = parts["html"]
        new_html = _insert_html(get_text(part), html_banner(ctx, reply_to), top)
        set_text(part, new_html, is_root=part is msg)
    return msg
