"""Tests for build_forward: headers, banner, trackers, special MIME shapes and round-tripping."""

# 1st party imports
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from typing import cast

# 3rd party imports
import pytest

# local imports
from mailalias.mail.transform.banner import HTML_END, HTML_START, TEXT_END, TEXT_START
from mailalias.mail.transform.context import BannerPosition, BannerSettings, TransformContext
from mailalias.mail.transform.forward import build_forward
from mailalias.mail.transform.mime import body_parts, get_text
from tests.eml import load_eml

ALIAS = "shop.fox42@closetcompute.online"
TOKEN_ADDRESS = "abcdefghijklmnop@rp.closetcompute.online"
FIXTURES = (
    "fwd_plain.eml",
    "fwd_html_only.eml",
    "fwd_alternative.eml",
    "fwd_attachments.eml",
    "fwd_reply_to.eml",
    "fwd_latin1.eml",
    "fwd_signed.eml",
    "fwd_encrypted.eml",
    "fwd_attachment_only.eml",
    "real_inbound_gmail.eml",
)


def _ctx(position: BannerPosition = "top", strip: bool = True) -> TransformContext:
    """A transform context for the test alias.

    Args:
        position: Banner position.
        strip: Strip trackers.
    Returns:
        The context.
    """
    return TransformContext(
        alias_address=ALIAS,
        contact_token_address=TOKEN_ADDRESS,
        sender_display="Alice (alice at example.org)",
        banner=BannerSettings(
            position=position,
            block_sender_url="https://app.closetcompute.online/a/block-token",
            disable_alias_url="https://app.closetcompute.online/a/disable-token",
        ),
        strip_trackers=strip,
        pgp_public_key=None,
        pgp_protect_subject=False,
    )


def _roundtrip(msg: EmailMessage) -> EmailMessage:
    """Serialise and parse back, asserting no MIME defects anywhere.

    Args:
        msg: Built message.
    Returns:
        The reparsed message.
    """
    parsed = cast(EmailMessage, BytesParser(policy=policy.default).parsebytes(msg.as_bytes()))
    for part in parsed.walk():
        assert not part.defects, part.defects
    return parsed


def _texts(msg: EmailMessage) -> dict[str, str]:
    """Decoded body texts.

    Args:
        msg: Message.
    Returns:
        Mapping "plain"/"html" -> text.
    """
    return {subtype: get_text(part) for subtype, part in body_parts(msg).items()}


@pytest.mark.parametrize("fixture", FIXTURES)
def test_every_fixture_round_trips_with_token_sender(fixture: str) -> None:
    """All shapes produce defect-free MIME with the token From and a banner."""
    original = load_eml(fixture)
    before = original.as_bytes()
    out = _roundtrip(build_forward(original, _ctx()))
    assert original.as_bytes() == before  # the input is never modified
    assert out["From"].addresses[0].addr_spec == TOKEN_ADDRESS
    assert out["From"].addresses[0].display_name == "Alice (alice at example.org)"
    assert str(out["Reply-To"]) == str(out["From"])
    assert out["X-Closet-Alias"] == ALIAS
    assert out["Message-ID"] is None
    texts = _texts(out)
    assert texts, "a text body must always exist"
    assert any(TEXT_START in text or HTML_START in text for text in texts.values())


def test_transport_headers_removed_and_threading_kept() -> None:
    """Traces, receipts and spoofed X-Closet headers go; threading headers stay."""
    out = _roundtrip(build_forward(load_eml("fwd_plain.eml"), _ctx()))
    for name in (
        "Received",
        "Authentication-Results",
        "DKIM-Signature",
        "Return-Path",
        "Delivered-To",
        "X-Original-To",
        "Disposition-Notification-To",
    ):
        assert out[name] is None, name
    assert out.get_all("X-Closet-Alias") == [ALIAS]
    assert out["To"] == ALIAS
    assert "carol@example.org" in str(out["Cc"])
    assert out["Subject"] == "Plain hello"
    assert out["In-Reply-To"] == "<older0001@example.org>"
    assert str(out["References"]).split() == [
        "<root0001@example.org>",
        "<older0001@example.org>",
        "<plain0001@example.org>",
    ]


def test_text_banner_top_and_bottom() -> None:
    """Text banner markers wrap the alias, sender and both action links."""
    top = _texts(build_forward(load_eml("fwd_plain.eml"), _ctx("top")))["plain"]
    assert top.startswith(TEXT_START)
    assert f"Sent to {ALIAS} from Alice (alice at example.org)" in top
    assert "Block sender: https://app.closetcompute.online/a/block-token" in top
    assert top.index(TEXT_END) < top.index("Hello, this is plain text.")
    bottom = _texts(build_forward(load_eml("fwd_plain.eml"), _ctx("bottom")))["plain"]
    assert bottom.rstrip().endswith(TEXT_END)


def test_html_banner_placement() -> None:
    """HTML banner goes right after <body ...> (any case) or before </body>."""
    top = _texts(build_forward(load_eml("fwd_alternative.eml"), _ctx("top")))
    assert '<BODY style="x">' + HTML_START in top["html"]
    assert TEXT_START in top["plain"]
    bottom = _texts(build_forward(load_eml("fwd_alternative.eml"), _ctx("bottom")))["html"]
    assert HTML_END + "</BODY>" in bottom


def test_banner_off() -> None:
    """Position off leaves bodies without markers."""
    texts = _texts(build_forward(load_eml("fwd_alternative.eml"), _ctx("off")))
    assert all(TEXT_START not in t and HTML_START not in t for t in texts.values())


def test_banner_values_are_escaped() -> None:
    """Sender-controlled display names cannot inject HTML."""
    ctx = _ctx()
    evil = TransformContext(**{**ctx.__dict__, "sender_display": "<script>x</script>"})
    html_text = _texts(build_forward(load_eml("fwd_alternative.eml"), evil))["html"]
    assert "<script>" not in html_text and "&lt;script&gt;" in html_text


def test_trackers_removed_and_real_images_kept() -> None:
    """1px, hidden, zero-size-style and known-host images go; content images stay."""
    html_text = _texts(build_forward(load_eml("fwd_html_only.eml"), _ctx()))["html"]
    assert "hero.jpg" in html_text
    for tracker in ("o.gif", "list-manage.com", "p.gif", "q.gif"):
        assert tracker not in html_text, tracker
    kept = _texts(build_forward(load_eml("fwd_html_only.eml"), _ctx(strip=False)))["html"]
    assert "o.gif" in kept


def test_list_unsubscribe_mailto_dropped() -> None:
    """mailto: entries are removed; https: kept; empty header and its Post companion go."""
    html_out = build_forward(load_eml("fwd_html_only.eml"), _ctx())
    assert html_out["List-Unsubscribe"] == "<https://shop.example/u/123>"
    assert html_out["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    mailto_only = build_forward(load_eml("fwd_reply_to.eml"), _ctx())
    assert mailto_only["List-Unsubscribe"] is None
    assert mailto_only["List-Unsubscribe-Post"] is None


def test_differing_reply_to_shown_in_banner() -> None:
    """A Reply-To that differs from From is disclosed, then replaced by the token."""
    out = build_forward(load_eml("fwd_reply_to.eml"), _ctx())
    assert "replies to go to: support@helpdesk.example" in _texts(out)["plain"]
    assert out["Reply-To"].addresses[0].addr_spec == TOKEN_ADDRESS
    same = _texts(build_forward(load_eml("fwd_plain.eml"), _ctx()))["plain"]
    assert "replies to go to" not in same


def test_attachments_and_inner_message_untouched() -> None:
    """Only the body gets the banner; attachments and message/rfc822 stay byte-identical."""
    out = _roundtrip(build_forward(load_eml("fwd_attachments.eml"), _ctx()))
    attachments = {part.get_filename(): part for part in out.iter_attachments()}
    assert attachments["report.pdf"].get_content() == b"%PDF-1.4\n% synthetic\n"
    assert TEXT_START not in get_text(attachments["notes.txt"])  # type: ignore[arg-type]
    inner = next(p for p in out.walk() if p.get_content_type() == "message/rfc822")
    assert TEXT_START not in inner.as_string()


def test_latin1_charset_preserved() -> None:
    """Non-UTF-8 text keeps its charset when the banner fits in it."""
    out = _roundtrip(build_forward(load_eml("fwd_latin1.eml"), _ctx()))
    assert out.get_content_charset() == "iso-8859-1"
    text = _texts(out)["plain"]
    assert "Un café crème" in text and TEXT_START in text
    assert out["Subject"] == "Café"


def test_latin1_falls_back_to_utf8_for_unencodable_banner() -> None:
    """A banner the original charset cannot encode switches the part to UTF-8."""
    ctx = _ctx()
    cjk = TransformContext(**{**ctx.__dict__, "sender_display": "山田 (yamada at example.jp)"})
    out = _roundtrip(build_forward(load_eml("fwd_latin1.eml"), cjk))
    assert out.get_content_charset() == "utf-8"
    assert "山田" in _texts(out)["plain"] and "café" in _texts(out)["plain"]


def test_signed_mail_is_treated_as_normal() -> None:
    """multipart/signed gets the banner (the relay rebuilds it anyway); signature kept."""
    out = _roundtrip(build_forward(load_eml("fwd_signed.eml"), _ctx()))
    assert TEXT_START in _texts(out)["plain"]
    assert any(p.get_content_type() == "application/pgp-signature" for p in out.walk())


def test_encrypted_mail_is_repackaged() -> None:
    """multipart/encrypted becomes a notice plus encrypted.asc."""
    out = _roundtrip(build_forward(load_eml("fwd_encrypted.eml"), _ctx()))
    assert out.get_content_type() == "multipart/mixed"
    assert out["X-Closet-Notice"] == "pgp-mime-repackaged"
    assert out["Subject"] == "Encrypted message"
    assert "PGP/MIME encrypted" in _texts(out)["plain"]
    (attachment,) = list(out.iter_attachments())
    assert attachment.get_filename() == "encrypted.asc"
    assert b"BEGIN PGP MESSAGE" in attachment.get_content()


def test_attachment_only_mail_gains_text_body() -> None:
    """A body-less message gets a text part so the relay accepts it."""
    out = _roundtrip(build_forward(load_eml("fwd_attachment_only.eml"), _ctx("off")))
    assert "no text body" in _texts(out)["plain"]
    (attachment,) = list(out.iter_attachments())
    assert attachment.get_filename() == "scan.png"
