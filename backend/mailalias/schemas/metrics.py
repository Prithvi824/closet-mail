"""Response models for metrics: the operator overview and one subdomain's activity."""

# 1st party imports
import uuid
from datetime import date, datetime

# 3rd party imports
from pydantic import BaseModel

# local imports
from mailalias.mail.types import MailKind, Outcome
from mailalias.models import DeliveryStatus


class OutcomeTotals(BaseModel):
    """Mail counts over a window: received forwards by outcome, plus replies sent."""

    received: int
    delivered: int
    quarantined: int
    blocked: int
    discarded: int
    replies: int


class DailyPoint(BaseModel):
    """One UTC day (by the time the mail was received)."""

    day: date
    received: int
    delivered: int
    replies: int


class CountItem(BaseModel):
    """A sender domain, sender address, alias address or inbox, with its count."""

    key: str
    count: int


class SubdomainTotals(BaseModel):
    """One subdomain's numbers on the overview."""

    label: str
    display_name: str | None
    totals: OutcomeTotals
    sends_today: int
    send_share: int


class OverviewResponse(BaseModel):
    """Every subdomain together over `days` days."""

    days: int
    totals: OutcomeTotals
    daily: list[DailyPoint]
    per_subdomain: list[SubdomainTotals]
    top_sender_domains: list[CountItem]
    sends_today: int
    send_cap: int


class Destination(BaseModel):
    """Where one copy went (inbox is None for a reply) and what the provider reported."""

    inbox: str | None
    status: DeliveryStatus


class MailEvent(BaseModel):
    """One handled message: when, from whom, to which alias, and to which inboxes."""

    id: uuid.UUID
    received_at: datetime
    kind: MailKind
    outcome: Outcome
    reason: str | None
    alias_address: str | None
    sender: str | None
    sender_domain: str | None
    destinations: list[Destination]
    spam_score: float | None
    size_bytes: int


class SubdomainActivityResponse(BaseModel):
    """One subdomain over `days` days, with a page of recent mail (newest first)."""

    days: int
    totals: OutcomeTotals
    daily: list[DailyPoint]
    top_sender_domains: list[CountItem]
    top_senders: list[CountItem]
    per_alias: list[CountItem]
    per_inbox: list[CountItem]
    recent: list[MailEvent]
    page: int
    has_more: bool
