"""Tests for inline PGP on forwards: everything encrypted, decryptable, nothing left in clear."""

# 1st party imports
import dataclasses
import tempfile
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from typing import cast

# 3rd party imports
import gnupg
import pytest

# local imports
from mailalias.mail.transform.banner import HTML_START, TEXT_START
from mailalias.mail.transform.context import BannerSettings, TransformContext
from mailalias.mail.transform.forward import build_forward
from mailalias.mail.transform.pgp import HTML_FILENAME, PGP_ARMOR, PROTECTED_SUBJECT
from tests.eml import load_eml
from tests.pgp_keys import PgpTestKey, make_key


@pytest.fixture(scope="module")
def key() -> PgpTestKey:
    """One throwaway key pair for the module.

    Returns:
        The key.
    """
    return make_key("owner@example.com")


def _ctx(key: PgpTestKey, protect_subject: bool = False) -> TransformContext:
    """Forward context with the recipient's public key.

    Args:
        key: Test key.
        protect_subject: Hide the subject.
    Returns:
        The context.
    """
    return TransformContext(
        alias_address="shop@closetcompute.online",
        contact_token_address="aaaaaaaaaaaaaaaa@rp.closetcompute.online",
        sender_display="Alice (alice at example.org)",
        banner=BannerSettings("top", "https://app.test/a/b", "https://app.test/a/d"),
        strip_trackers=True,
        pgp_public_key=key.public,
        pgp_protect_subject=protect_subject,
    )


def _decrypt(data: bytes, key: PgpTestKey) -> bytes:
    """Decrypt with the private key in a scratch keyring.

    Args:
        data: Armored PGP message.
        key: Test key.
    Returns:
        Plaintext bytes.
    """
    with tempfile.TemporaryDirectory() as home:
        gpg = gnupg.GPG(gnupghome=home)
        gpg.import_keys(key.private)
        result = gpg.decrypt(data, always_trust=True)
        assert result.ok, result.status
        return bytes(result.data)


def _build(name: str, key: PgpTestKey, protect: bool = False) -> EmailMessage:
    """Build a forward and reparse it, asserting no MIME defects.

    Args:
        name: Fixture name.
        key: Test key.
        protect: Protect the subject.
    Returns:
        The reparsed output.
    """
    out = build_forward(load_eml(name), _ctx(key, protect))
    parsed = cast(EmailMessage, BytesParser(policy=policy.default).parsebytes(out.as_bytes()))
    assert all(not part.defects for part in parsed.walk())
    return parsed


def test_every_part_is_encrypted_and_decrypts(key: PgpTestKey) -> None:
    """Text (with banner), HTML and each attachment come back intact; no plaintext remains."""
    out = _build("fwd_attachments.eml", key)
    assert out.get_content_type() == "multipart/mixed"
    body = out.get_body(("plain",))
    assert body is not None and body.get_content().startswith(PGP_ARMOR)
    text = _decrypt(body.get_content().encode(), key).decode()
    assert TEXT_START in text and "See attached." in text
    files = {part.get_filename(): part.get_content() for part in out.iter_attachments()}
    assert set(files) == {HTML_FILENAME, "report.pdf.pgp", "notes.txt.pgp", "message-3.eml.pgp"}
    assert HTML_START in _decrypt(files[HTML_FILENAME], key).decode()
    assert _decrypt(files["notes.txt.pgp"], key) == b"attached notes, not a body"
    assert b"Inner forwarded mail" in _decrypt(files["message-3.eml.pgp"], key)
    raw = out.as_bytes()
    for clear in (b"See attached.", b"attached notes", b"Inner forwarded mail", b"closet-banner"):
        assert clear not in raw, clear
    assert out["Subject"] == "Files attached"


def test_html_only_mail_gets_extracted_text_body(key: PgpTestKey) -> None:
    """Without a text part, the encrypted body is text extracted from the HTML."""
    out = _build("fwd_html_only.eml", key)
    body = out.get_body(("plain",))
    assert body is not None
    text = _decrypt(body.get_content().encode(), key).decode()
    assert "Sent to shop@closetcompute.online" in text and "<" not in text
    assert [p.get_filename() for p in out.iter_attachments()] == [HTML_FILENAME]


def test_protected_subject_moves_inside(key: PgpTestKey) -> None:
    """The outer subject becomes "..."; the real one heads the encrypted text."""
    out = _build("fwd_plain.eml", key, protect=True)
    assert out["Subject"] == PROTECTED_SUBJECT
    body = out.get_body(("plain",))
    assert body is not None
    original = str(load_eml("fwd_plain.eml")["Subject"])
    assert (
        _decrypt(body.get_content().encode(), key).decode().startswith(f"Subject: {original}\n\n")
    )


def test_already_encrypted_mail_is_not_encrypted_again(key: PgpTestKey) -> None:
    """PGP/MIME input stays the repackaged notice plus encrypted.asc."""
    out = _build("fwd_encrypted.eml", key)
    assert out["X-Closet-Notice"] == "pgp-mime-repackaged"
    assert [p.get_filename() for p in out.iter_attachments()] == ["encrypted.asc"]


def test_inline_armor_is_not_encrypted_again_under_a_top_banner(key: PgpTestKey) -> None:
    """An inline-PGP body stays as is even though the top banner now precedes the armor."""
    original = EmailMessage()
    original["From"] = "alice@example.org"
    original["To"] = "shop@closetcompute.online"
    original["Subject"] = "secret"
    armor = f"{PGP_ARMOR}\n\nhQEMA1234\n-----END PGP MESSAGE-----\n"
    original.set_content(armor)
    out = build_forward(original, _ctx(key))
    body = out.get_body(("plain",))
    assert body is not None
    text = cast(EmailMessage, body).get_content()
    assert TEXT_START in text and text.count(PGP_ARMOR) == 1 and "hQEMA1234" in text


def test_no_key_means_no_encryption(key: PgpTestKey) -> None:
    """Recipients without a key get the normal forward."""
    ctx = dataclasses.replace(_ctx(key), pgp_public_key=None)
    out = build_forward(load_eml("fwd_plain.eml"), ctx)
    body = out.get_body(("plain",))
    assert body is not None and TEXT_START in body.get_content()
