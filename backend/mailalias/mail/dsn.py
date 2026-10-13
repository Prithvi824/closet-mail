"""Detect and parse delivery status notifications (RFC 3464 bounces)."""

# 1st party imports
from dataclasses import dataclass
from email.message import EmailMessage, Message

DELIVERY_STATUS = "message/delivery-status"


@dataclass(frozen=True)
class DsnInfo:
    """The first per-recipient result of a DSN."""

    action: str  # "failed" | "delayed" | "delivered" | "relayed" | "expanded" | ""
    status: str  # enhanced status code, e.g. "5.1.1"
    final_recipient: str
    diagnostic: str | None = None

    @property
    def is_hard(self) -> bool:
        """Whether this is a permanent failure.

        Returns:
            True for action "failed" with a 5.x.x status.
        """
        return self.action == "failed" and self.status.startswith("5")


def _status_part(msg: EmailMessage) -> Message | None:
    """Find the message/delivery-status part, if any.

    Args:
        msg: Parsed message.
    Returns:
        The part, or None.
    """
    for part in msg.walk():
        if part.get_content_type() == DELIVERY_STATUS:
            return part
    return None


def is_dsn(msg: EmailMessage, mail_from: str | None = None) -> bool:
    """Whether a message is a delivery status notification.

    Args:
        msg: Parsed message.
        mail_from: Envelope sender when known ("" is the null sender).
    Returns:
        True for multipart/report; report-type=delivery-status, or a null-sender message
        that contains a delivery-status part.
    """
    if (
        msg.get_content_type() == "multipart/report"
        and str(msg.get_param("report-type", "")).lower() == "delivery-status"
    ):
        return True
    return mail_from == "" and _status_part(msg) is not None


def _field_blocks(part: Message) -> list[Message]:
    """The header blocks of a delivery-status part (per-message first, then per-recipient).

    Args:
        part: The message/delivery-status part.
    Returns:
        List of header-only messages.
    """
    payload = part.get_payload()
    return (
        [block for block in payload if isinstance(block, Message)]
        if isinstance(payload, list)
        else []
    )


def _strip_type(value: str) -> str:
    """Drop the "rfc822;" / "smtp;" type prefix of a DSN field.

    Args:
        value: Field value.
    Returns:
        The value after the first ";", stripped.
    """
    return value.split(";", 1)[1].strip() if ";" in value else value.strip()


def parse_dsn(msg: EmailMessage) -> DsnInfo | None:
    """Read the first per-recipient block of a DSN.

    Args:
        msg: A message for which is_dsn() is True.
    Returns:
        DsnInfo, or None when no per-recipient block with an Action is present.
    """
    part = _status_part(msg)
    if part is None:
        return None
    for block in _field_blocks(part):
        action = str(block.get("Action", "")).strip().lower()
        if not action:
            continue
        recipient = block.get("Final-Recipient") or block.get("Original-Recipient") or ""
        diagnostic = block.get("Diagnostic-Code")
        return DsnInfo(
            action=action,
            status=str(block.get("Status", "")).strip(),
            final_recipient=_strip_type(str(recipient)).lower(),
            diagnostic=_strip_type(str(diagnostic)) if diagnostic else None,
        )
    return None
