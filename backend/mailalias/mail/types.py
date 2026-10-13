"""Core mail-pipeline types shared by the processor, handlers and models (interface contract)."""

# 1st party imports
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class MailKind(StrEnum):
    """What the classifier decided an inbound message is."""

    FORWARD = "forward"
    REPLY = "reply"
    BOUNCE = "bounce"
    DROP = "drop"


class Outcome(StrEnum):
    """Final result of handling one inbound message."""

    DELIVERED = "delivered"
    DISCARDED = "discarded"
    QUARANTINED = "quarantined"
    BLOCKED = "blocked"
    REJECTED_REPLY = "rejected_reply"
    BOUNCE_RECORDED = "bounce_recorded"


@dataclass(frozen=True)
class InboundEnvelope:
    """One job pulled from the inbound Queue, plus its lease."""

    lease_id: str
    attempts: int
    r2_key: str
    mail_from: str
    rcpt_to: str
    raw_size: int
    received_at: datetime


@dataclass(frozen=True)
class AuthResults:
    """SPF/DKIM/DMARC verdicts from a trusted Authentication-Results header."""

    spf: str  # "pass" | "fail" | "softfail" | "neutral" | "none" | "temperror" | "permerror"
    dkim: str
    dmarc: str
    from_domain: str
    dmarc_policy: str = "none"  # sender domain's published p= ("none" | "quarantine" | "reject")


@dataclass(frozen=True)
class HandlerResult:
    """What a handler did with a message, for logging and the mail log."""

    outcome: Outcome
    reason: str | None = None


class RetryableError(Exception):
    """Infrastructure failure: do not ack; the Queue will redeliver."""

    def __init__(self, message: str, delay_seconds: int | None = None) -> None:
        """Create the error.

        Args:
            message: Description safe to log (no secrets, no addresses).
            delay_seconds: Requested redelivery delay; None lets the processor back off.
        Returns:
            None.
        """
        super().__init__(message)
        self.delay_seconds = delay_seconds
