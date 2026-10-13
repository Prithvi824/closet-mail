"""Read SPF/DKIM/DMARC verdicts that Cloudflare Email Routing stamped on an inbound message.

Only the topmost Authentication-Results / Received-SPF headers are trusted, and only when they
carry Cloudflare's authserv-id: anything below them was written by the sender and may be forged.
"""

# 1st party imports
import re
from email.message import EmailMessage
from email.utils import parseaddr

# local imports
from mailalias.mail.types import AuthResults

TRUSTED_AUTHSERV_ID = "mx.cloudflare.net"
KNOWN_RESULTS = frozenset(
    {"pass", "fail", "softfail", "neutral", "none", "temperror", "permerror", "policy"}
)
COMMENT_RE = re.compile(r"\([^()]*\)")
WHITESPACE_RE = re.compile(r"\s+")


def _strip_comments(value: str) -> str:
    """Remove RFC 5322 comments (repeatedly, for nesting) and collapse whitespace.

    Args:
        value: Raw header value.
    Returns:
        The value without parenthesised comments, single-spaced.
    """
    previous = None
    while previous != value:
        previous, value = value, COMMENT_RE.sub(" ", value)
    return WHITESPACE_RE.sub(" ", value).strip()


def _result(value: str) -> str:
    """Normalise a verdict word; anything unrecognised becomes "none".

    Args:
        value: Verdict as written in the header.
    Returns:
        A lowercase verdict from KNOWN_RESULTS.
    """
    value = value.strip().lower()
    return value if value in KNOWN_RESULTS else "none"


def _parse_resinfo(header: str) -> tuple[str, list[tuple[str, str, dict[str, str]]]]:
    """Split an Authentication-Results value into authserv-id and method results.

    Args:
        header: Header value.
    Returns:
        (authserv-id, [(method, result, {property: value})]).
    """
    authserv, *clauses = _strip_comments(header).split(";")
    results = []
    for clause in clauses:
        tokens = clause.split()
        if not tokens or "=" not in tokens[0]:
            continue
        method, result = tokens[0].split("=", 1)
        props = dict(token.split("=", 1) for token in tokens[1:] if "=" in token)
        results.append((method.lower(), _result(result), props))
    authserv_id = authserv.split()[0].lower() if authserv.split() else ""
    return authserv_id, results


def _from_domain(msg: EmailMessage) -> str:
    """Domain of the RFC 5322 From header.

    Args:
        msg: Parsed message.
    Returns:
        Lowercased domain, or "" when missing.
    """
    _, address = parseaddr(str(msg.get("From", "")))
    return address.rpartition("@")[2].lower()


def _received_spf(msg: EmailMessage) -> str | None:
    """SPF verdict for the envelope sender from Cloudflare's own Received-SPF header.

    Args:
        msg: Parsed message.
    Returns:
        The verdict, or None when the topmost Received-SPF is missing or not Cloudflare's.
    """
    headers = msg.get_all("Received-SPF") or []
    if not headers:
        return None
    top = WHITESPACE_RE.sub(" ", str(headers[0])).strip()
    if f"receiver={TRUSTED_AUTHSERV_ID}" not in top and f"({TRUSTED_AUTHSERV_ID}:" not in top:
        return None
    return _result(top.split(" ", 1)[0])


def parse(msg: EmailMessage) -> AuthResults:
    """Extract trusted SPF/DKIM/DMARC verdicts.

    Args:
        msg: Parsed inbound message.
    Returns:
        AuthResults; every verdict is "none" when no trusted header exists.
    """
    headers = msg.get_all("Authentication-Results") or []
    authserv_id, results = _parse_resinfo(str(headers[0])) if headers else ("", [])
    if authserv_id != TRUSTED_AUTHSERV_ID:
        results = []

    dkim_results = [result for method, result, _ in results if method == "dkim"]
    # Several signatures may be present; one valid signature is enough.
    dkim = "pass" if "pass" in dkim_results else (dkim_results[0] if dkim_results else "none")
    dmarc, policy, from_domain = "none", "none", _from_domain(msg)
    header_spf = "none"
    for method, result, props in results:
        if method == "dmarc":
            dmarc = result
            policy = props.get("policy.dmarc", "none").lower()
            from_domain = props.get("header.from", from_domain).lower()
        elif method == "spf" and "smtp.mailfrom" in props:
            header_spf = result
    spf = (_received_spf(msg) if results else None) or header_spf
    return AuthResults(
        spf=spf, dkim=dkim, dmarc=dmarc, from_domain=from_domain, dmarc_policy=policy
    )


CLOUDFLARE_RECEIVED_RE = re.compile(
    r"^\s*from\s+(?P<helo>\S+)\s+\((?P<ip>[0-9A-Fa-f:.]+)\)\s+by\s+cloudflare-email\.net\b"
)


def client_info(msg: EmailMessage) -> tuple[str | None, str | None]:
    """The connecting client's IP and HELO, from Cloudflare's own (topmost) Received header.

    Args:
        msg: Parsed inbound message.
    Returns:
        (ip, helo); both None when the top header is not Cloudflare's.
    """
    received = msg.get_all("Received", [])
    match = CLOUDFLARE_RECEIVED_RE.match(str(received[0])) if received else None
    return (match["ip"], match["helo"]) if match else (None, None)
