"""Tests for build_reply: alias identity, owner scrubbing, banner removal, threading."""

# 1st party imports
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

# local imports
from mailalias.mail.transform.context import ReplyContext
from mailalias.mail.transform.reply import build_reply
from tests.eml import EML_DIR, load_eml

ALIAS = "shop@closetcompute.online"
OWNER = "pia@example.com"
TOKEN = "aaaaaaaaaaaaaaaa"
TOKEN_ADDRESS = f"{TOKEN}@rp.closetcompute.online"


def owner_reply(dmarc: str = "pass", cc: str = "Nobody <nobody@example.org>") -> EmailMessage:
    """Fill the owner-reply fixture template.

    Args:
        dmarc: DMARC verdict to stamp.
        cc: Cc header value.
    Returns:
        Parsed message.
    """
    raw = (EML_DIR / "owner_reply_gmail.eml").read_text()
    raw = raw.replace("{TOKEN}", TOKEN).replace("{FROM}", OWNER)
    raw = raw.replace("{DMARC}", dmarc).replace("{CC}", cc)
    return BytesParser(policy=policy.default).parsebytes(raw.encode())


def _ctx() -> ReplyContext:
    """Reply context for one same-alias contact.

    Returns:
        The context.
    """
    return ReplyContext(
        alias_address=ALIAS,
        to=(("Bob", "bob@example.net"),),
        cc=(),
        owner_addresses=(OWNER, "pia.other@example.com"),
        token_addresses={TOKEN_ADDRESS: "bob@example.net"},
        action_url_prefix="https://app.closetcompute.online/a/",
    )


def test_reply_has_alias_identity_and_real_recipients() -> None:
    """From is the alias; To/Cc are the mapped real addresses only."""
    out = build_reply(owner_reply(), _ctx())
    assert out["From"] == ALIAS
    assert out["To"].addresses[0].addr_spec == "bob@example.net"
    assert out["Cc"] is None
    assert out["Reply-To"] is None and out["Message-ID"] is None
    assert out["Subject"] == "Re: Alternative parts"


def test_no_owner_address_token_or_action_link_in_raw_bytes() -> None:
    """The full serialised reply never mentions the owner, tokens or signed links."""
    raw = build_reply(owner_reply(), _ctx()).as_bytes().lower()
    for leak in (OWNER, TOKEN_ADDRESS, "/a/eyj", "closet-banner", "x-gm-", "x-google-"):
        assert leak.encode() not in raw, leak
    assert b"write to me at shop@closetcompute.online" in raw
    for header in (b"received:", b"dkim-signature:", b"authentication-results:", b"arc-seal:"):
        assert header not in raw


def test_banner_removed_from_quotes_but_quote_kept() -> None:
    """Quoted banners go (text markers and marker-less HTML); the quoted content stays."""
    out = build_reply(owner_reply(), _ctx())
    text = out.get_body(("plain",)).get_content()  # type: ignore[union-attr]
    html = out.get_body(("html",)).get_content()  # type: ignore[union-attr]
    assert "> Text version." in text and "Sent to shop@" not in text
    assert "HTML version." in html and "Sent to" not in html
    assert "bob@example.net" in text  # quoted token address rewritten to the real one


def test_threading_drops_relay_ids() -> None:
    """SES ids leave References/In-Reply-To; In-Reply-To points at the original."""
    out = build_reply(owner_reply(), _ctx())
    assert str(out["References"]) == "<orig0001@example.org>"
    assert str(out["In-Reply-To"]) == "<orig0001@example.org>"


def test_encrypted_reply_is_repackaged() -> None:
    """A PGP/MIME reply becomes a notice plus encrypted.asc."""
    encrypted = load_eml("fwd_encrypted.eml")
    out = build_reply(encrypted, _ctx())
    assert out.get_content_type() == "multipart/mixed"
    assert [p.get_filename() for p in out.iter_attachments()] == ["encrypted.asc"]
    assert out["From"] == ALIAS


def test_marker_less_text_banner_rendered_by_gmail_is_removed() -> None:
    """Gmail rebuilds text/plain from quoted HTML: banner wording survives without markers."""
    msg = owner_reply()
    body = msg.get_body(("plain",))
    assert body is not None
    body.set_content(
        "Thanks!\n\nOn Mon, Bob <" + TOKEN_ADDRESS + "> wrote:\n\n"
        f"> Sent to *{ALIAS}* from Bob (bob at example.net) · Block sender\n"
        "> · Disable alias\n> Original line.\n"
    )
    text = build_reply(msg, _ctx()).get_body(("plain",)).get_content()  # type: ignore[union-attr]
    assert "Sent to" not in text and "Disable alias" not in text
    assert "> Original line." in text and "<bob@example.net> wrote:" in text


def test_address_rewrite_matches_whole_addresses_only() -> None:
    """An owner address inside a longer address is left alone; rewrites are not chained."""
    msg = owner_reply()
    body = msg.get_body(("plain",))
    assert body is not None
    body.set_content(f"cc xpia@example.com, {OWNER}.au and {OWNER}.\n")
    text = build_reply(msg, _ctx()).get_body(("plain",)).get_content()  # type: ignore[union-attr]
    assert text.strip() == f"cc xpia@example.com, {OWNER}.au and {ALIAS}."
