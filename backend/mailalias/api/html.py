"""Minimal server-rendered HTML pages for links opened from email (verify, one-click actions)."""

# 1st party imports
from html import escape

# 3rd party imports
from fastapi.responses import HTMLResponse

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{title}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;
padding:0 1rem;color:#1f2937}}
button{{font:inherit;padding:.6rem 1.2rem;border:0;border-radius:.4rem;
background:#2563eb;color:#fff;cursor:pointer}}
</style></head>
<body><h1>{title}</h1><p>{message}</p>{form}</body></html>"""


def simple_page(
    title: str,
    message: str,
    *,
    button: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Render a small page, optionally with a POST-to-self confirmation button.

    Args:
        title: Page heading.
        message: Plain-text explanation (escaped).
        button: Label for a confirmation button that POSTs to the same URL.
        status_code: HTTP status.
    Returns:
        The HTML response (never cached, never framed).
    """
    form = (
        f'<form method="post"><button type="submit">{escape(button)}</button></form>'
        if button
        else ""
    )
    html = _PAGE.format(title=escape(title), message=escape(message), form=form)
    return HTMLResponse(
        html,
        status_code=status_code,
        headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"},
    )
