"""Subdomain status: the latest routing check of one subdomain (DNS, KV flag, inboxes)."""

# 1st party imports
import uuid
from datetime import datetime
from enum import StrEnum

# 3rd party imports
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

# local imports
from mailalias.models.base import Base, Timestamps, pg_enum


class SubdomainState(StrEnum):
    """Overall readiness of a subdomain to receive mail."""

    READY = "ready"
    DNS_MISSING = "dns_missing"
    NO_INBOX = "no_inbox"
    SUSPENDED = "suspended"
    RETIRED = "retired"
    UNKNOWN = "unknown"


class SubdomainStatus(Timestamps, Base):
    """One row per subdomain (users row), replaced on every check."""

    __tablename__ = "subdomain_status"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[SubdomainState] = mapped_column(pg_enum(SubdomainState, "subdomain_state"))
    mx_ok: Mapped[bool | None]
    spf_ok: Mapped[bool | None]
    kv_ok: Mapped[bool | None]
    detail: Mapped[str | None] = mapped_column(String(200))
    checked_at: Mapped[datetime]
