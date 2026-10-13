"""T4/T15 spike: send probe messages through the Resend SMTP relay to SPIKE_TO.

Run from backend/: `uv run python ../deploy/scripts/spike_resend.py [probe letters, e.g. b d]`.
Prints only SMTP responses and message labels; never prints credentials or addresses.
"""

# 1st party imports
import asyncio
import sys
import tempfile
import uuid
from email.message import EmailMessage
from email.utils import formatdate

# 3rd party imports
import aiosmtplib
import gnupg

# local imports
from mailalias.config import get_settings

SYSTEM_FROM = "noreply@closetcompute.online"
RP_FROM = "spike@rp.closetcompute.online"


def _base(label: str, run_id: str, sender: str, to: str) -> EmailMessage:
    """Create a message with the common spike headers.

    Args:
        label: Probe letter (a-e).
        run_id: Short id tying the 5 messages together.
        sender: From address.
        to: Recipient address.
    Returns:
        A new EmailMessage without a body.
    """
    msg = EmailMessage()
    msg["From"] = f"Closet spike <{sender}>"
    msg["To"] = to
    msg["Subject"] = f"[spike {run_id} {label}] Resend relay probe"
    msg["Date"] = formatdate(localtime=False)
    return msg


def build_plain(run_id: str, to: str) -> EmailMessage:
    """(a) Plain text from the system address.

    Args:
        run_id: Spike run id.
        to: Recipient.
    Returns:
        The message.
    """
    msg = _base("a", run_id, SYSTEM_FROM, to)
    msg.set_content("Probe (a): plain text from noreply@closetcompute.online.\n")
    return msg


def build_rp_from(run_id: str, to: str) -> EmailMessage:
    """(b) From address on the rp. subdomain (reply-token domain).

    Args:
        run_id: Spike run id.
        to: Recipient.
    Returns:
        The message.
    """
    msg = _base("b", run_id, RP_FROM, to)
    msg["Reply-To"] = RP_FROM
    msg.set_content("Probe (b): From is on rp.closetcompute.online.\n")
    return msg


def build_threaded(run_id: str, to: str) -> tuple[EmailMessage, str]:
    """(c) multipart/alternative + attachment with custom Message-ID and threading headers.

    Args:
        run_id: Spike run id.
        to: Recipient.
    Returns:
        The message and the Message-ID we set (to compare with what arrives).
    """
    msg = _base("c", run_id, SYSTEM_FROM, to)
    message_id = f"<spike-{uuid.uuid4()}@closetcompute.online>"
    parent_id = f"<spike-parent-{run_id}@closetcompute.online>"
    msg["Message-ID"] = message_id
    msg["In-Reply-To"] = parent_id
    msg["References"] = parent_id
    msg.set_content("Probe (c): text part.\n")
    msg.add_alternative("<html><body><p>Probe (c): <b>HTML</b> part.</p></body></html>", "html")
    msg.add_attachment(
        b"spike attachment\n", maintype="text", subtype="plain", filename="spike.txt"
    )
    return msg, message_id


def build_pgp(run_id: str, to: str) -> EmailMessage:
    """(d) RFC 3156 PGP/MIME message encrypted to a throwaway key.

    Args:
        run_id: Spike run id.
        to: Recipient.
    Returns:
        The multipart/encrypted message.
    """
    with tempfile.TemporaryDirectory() as gpg_home:
        gpg = gnupg.GPG(gnupghome=gpg_home)
        key_input = gpg.gen_key_input(
            name_email="spike-key@closetcompute.online",
            key_type="RSA",
            key_length=2048,
            no_protection=True,
        )
        key = gpg.gen_key(key_input)
        inner = EmailMessage()
        inner.set_content("Probe (d): encrypted inner body.\n")
        encrypted = gpg.encrypt(inner.as_bytes(), str(key.fingerprint), armor=True)
        if not encrypted.ok:
            raise RuntimeError(f"gpg encrypt failed: {encrypted.status}")
        armored = str(encrypted)

    msg = _base("d", run_id, SYSTEM_FROM, to)
    msg.set_type("multipart/encrypted")
    msg.set_param("protocol", "application/pgp-encrypted")
    control = EmailMessage()
    control.set_content(b"Version: 1\n", maintype="application", subtype="pgp-encrypted")
    del control["Content-Transfer-Encoding"]
    control["Content-Transfer-Encoding"] = "7bit"
    payload = EmailMessage()
    payload.set_content(
        armored.encode(), maintype="application", subtype="octet-stream", filename="encrypted.asc"
    )
    del payload["Content-Transfer-Encoding"]
    payload["Content-Transfer-Encoding"] = "7bit"
    msg.attach(control)
    msg.attach(payload)
    return msg


def build_list_unsubscribe(run_id: str, to: str) -> EmailMessage:
    """(e) Message carrying a List-Unsubscribe header.

    Args:
        run_id: Spike run id.
        to: Recipient.
    Returns:
        The message.
    """
    msg = _base("e", run_id, SYSTEM_FROM, to)
    msg["List-Unsubscribe"] = "<https://example.com/u>"
    msg.set_content("Probe (e): has List-Unsubscribe.\n")
    return msg


def build_forward_shape(run_id: str, to: str) -> EmailMessage:
    """(f) Forward-shaped: header To is an unknown alias, the envelope recipient is SPIKE_TO.

    Shows whether Resend delivers to the SMTP envelope (required) or to header recipients
    (would loop forwards back to the alias). The unknown alias is rejected 550 at the edge.

    Args:
        run_id: Spike run id.
        to: Envelope recipient (not placed in any header).
    Returns:
        The message.
    """
    msg = _base("f", run_id, RP_FROM, f"probe-envelope-{run_id}@closetcompute.online")
    msg.set_content("Probe (f): header To differs from the SMTP envelope recipient.\n")
    return msg


async def main(only: set[str]) -> None:
    """Send the probes over one implicit-TLS SMTP session and print the 250 responses.

    Args:
        only: Probe letters to send; empty means all.
    Returns:
        None.
    """
    settings = get_settings()
    if not settings.spike_to:
        raise SystemExit("SPIKE_TO is not set in deploy/.env")
    to = settings.spike_to
    run_id = uuid.uuid4().hex[:6]
    threaded, message_id = build_threaded(run_id, to)
    probes = [
        ("a", build_plain(run_id, to)),
        ("b", build_rp_from(run_id, to)),
        ("c", threaded),
        ("d", build_pgp(run_id, to)),
        ("e", build_list_unsubscribe(run_id, to)),
        ("f", build_forward_shape(run_id, to)),
    ]
    probes = [(label, msg) for label, msg in probes if not only or label in only]
    print(f"run id: {run_id}  (search the inbox for 'spike {run_id}')")
    print(f"(c) Message-ID sent: {message_id}")
    smtp = aiosmtplib.SMTP(
        hostname=settings.resend_smtp_host, port=settings.resend_smtp_port, use_tls=True
    )
    async with smtp:
        await smtp.login("resend", settings.resend_api_key.get_secret_value())
        for label, msg in probes:
            sender = msg["From"].addresses[0].addr_spec
            try:
                _, response = await smtp.send_message(msg, sender=sender, recipients=[to])
                print(f"({label}) accepted: {response}")
            except aiosmtplib.SMTPException as exc:
                print(f"({label}) REJECTED: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main(set(sys.argv[1:])))
