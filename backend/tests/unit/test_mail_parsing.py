"""Tests for auth-results trust, DSN parsing and the classifier."""

# 1st party imports
from email.message import EmailMessage

# 3rd party imports
import pytest

# local imports
from mailalias.config import get_settings
from mailalias.mail import auth_results
from mailalias.mail.classifier import classify
from mailalias.mail.dsn import is_dsn, parse_dsn
from mailalias.mail.types import MailKind
from tests.eml import envelope, load_eml


def test_cloudflare_results_parsed_from_real_layout() -> None:
    """Gmail via Cloudflare: DKIM/DMARC from A-R, envelope SPF from Received-SPF."""
    results = auth_results.parse(load_eml("real_inbound_gmail.eml"))
    assert (results.dkim, results.dmarc, results.spf) == ("pass", "pass", "pass")
    assert results.from_domain == "gmail.com"
    assert results.dmarc_policy == "none"


def test_untrusted_authserv_id_is_ignored() -> None:
    """A sender-written header with a foreign authserv-id yields no verdicts."""
    results = auth_results.parse(load_eml("forged_auth_untrusted.eml"))
    assert (results.dkim, results.dmarc, results.spf) == ("none", "none", "none")
    assert results.from_domain == "bank.example"


def test_forged_header_below_cloudflare_is_ignored() -> None:
    """Only the topmost header counts, even if a lower one claims Cloudflare's id."""
    results = auth_results.parse(load_eml("forged_auth_below.eml"))
    assert results.dmarc == "fail"
    assert results.dmarc_policy == "reject"
    assert results.spf == "fail"
    assert results.dkim == "none"


def test_missing_headers_give_none() -> None:
    """No Authentication-Results at all."""
    msg = EmailMessage()
    msg["From"] = "x@y.example"
    results = auth_results.parse(msg)
    assert (results.dkim, results.dmarc, results.spf, results.from_domain) == (
        "none",
        "none",
        "none",
        "y.example",
    )


def test_one_passing_dkim_signature_is_enough() -> None:
    """Multiple dkim results: any pass wins."""
    msg = EmailMessage()
    msg["Authentication-Results"] = (
        "mx.cloudflare.net; dkim=fail header.d=a.example; dkim=pass header.d=b.example"
    )
    assert auth_results.parse(msg).dkim == "pass"


def test_dsn_detected_and_parsed() -> None:
    """multipart/report delivery-status is a DSN with a hard failure."""
    msg = load_eml("dsn_hard.eml")
    assert is_dsn(msg)
    info = parse_dsn(msg)
    assert info is not None
    assert (info.action, info.status) == ("failed", "5.1.1")
    assert info.final_recipient == "bob@example.org"
    assert info.diagnostic == "550 5.1.1 User unknown"
    assert info.is_hard


def test_null_sender_with_status_part_is_dsn() -> None:
    """A non-report wrapper still counts when the envelope sender is null."""
    status = EmailMessage()
    status.set_content("Final-Recipient: rfc822; c@d.example\nAction: delayed\nStatus: 4.4.1\n")
    msg = EmailMessage()
    msg.make_mixed()
    msg.attach(status)
    status.replace_header("Content-Type", "message/delivery-status")
    assert not is_dsn(msg, "someone@x.example")
    assert is_dsn(msg, "")


def test_plain_mail_is_not_dsn() -> None:
    """Ordinary mail is not a DSN even from the null sender."""
    msg = load_eml("real_inbound_gmail.eml")
    assert not is_dsn(msg, "")
    assert parse_dsn(msg) is None


@pytest.mark.parametrize(
    ("rcpt", "fixture", "mail_from", "kind"),
    [
        ("shop.fox42@closetcompute.online", "real_inbound_gmail.eml", "a@b.c", MailKind.FORWARD),
        ("x@alice.closetcompute.online", "real_inbound_gmail.eml", "a@b.c", MailKind.FORWARD),
        ("TOKEN@RP.closetcompute.online", "real_inbound_gmail.eml", "a@b.c", MailKind.REPLY),
        ("abcdefghijklmnop@rp.closetcompute.online", "dsn_hard.eml", "", MailKind.BOUNCE),
        ("x@a.b.closetcompute.online", "real_inbound_gmail.eml", "a@b.c", MailKind.DROP),
        ("x@other.example", "real_inbound_gmail.eml", "a@b.c", MailKind.DROP),
        ("x@closetcompute.online.evil.example", "real_inbound_gmail.eml", "a@b.c", MailKind.DROP),
        ("x@notclosetcompute.online", "real_inbound_gmail.eml", "a@b.c", MailKind.DROP),
        ("no-at-sign", "real_inbound_gmail.eml", "a@b.c", MailKind.DROP),
    ],
)
def test_classifier_table(rcpt: str, fixture: str, mail_from: str, kind: MailKind) -> None:
    """Routing by recipient domain."""
    msg = load_eml(fixture)
    assert classify(envelope(rcpt, mail_from), msg, get_settings()) is kind
