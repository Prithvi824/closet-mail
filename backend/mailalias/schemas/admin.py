"""Request/response models for the admin console."""

# 1st party imports
import uuid
from datetime import datetime
from typing import Any

# 3rd party imports
from pydantic import BaseModel, Field

# local imports
from mailalias.models import UserRole
from mailalias.services.admin import DlqItem, Health, UserSummary


class AdminUserResponse(BaseModel):
    """A user as seen by an admin."""

    id: uuid.UUID
    username: str
    email: str
    role: UserRole
    disabled: bool
    totp_enabled: bool
    limits: dict[str, int] | None
    alias_count: int
    created_at: datetime

    @classmethod
    def build(cls, summary: UserSummary) -> "AdminUserResponse":
        """Build from a service summary.

        Args:
            summary: User and alias count.
        Returns:
            The response model.
        """
        user = summary.user
        return cls(
            id=user.id,
            username=user.username,
            email=user.email,
            role=user.role,
            disabled=user.disabled_at is not None,
            totp_enabled=user.totp_enabled,
            limits=user.limits,
            alias_count=summary.alias_count,
            created_at=user.created_at,
        )


class AdminUserUpdate(BaseModel):
    """Partial update; `limits: null` resets to the defaults."""

    disabled: bool | None = None
    role: UserRole | None = None
    limits: dict[str, int] | None = Field(default=None)


class HealthResponse(BaseModel):
    """System health snapshot; null values could not be read."""

    heartbeat_age_seconds: float | None
    inbound_backlog: int | None
    dlq_backlog: int | None
    sends_today: int
    send_cap: int
    hard_bounces_7d: int
    complaints_7d: int
    kv_reconcile: dict[str, Any] | None

    @classmethod
    def build(cls, health: Health) -> "HealthResponse":
        """Build from the service snapshot.

        Args:
            health: Snapshot.
        Returns:
            The response model.
        """
        return cls(**vars(health))


class DlqItemResponse(BaseModel):
    """Metadata of a dead-lettered job."""

    lease_id: str
    r2_key: str
    rcpt_to: str
    raw_size: int
    received_at: datetime
    attempts: int

    @classmethod
    def build(cls, item: DlqItem) -> "DlqItemResponse":
        """Build from the service item.

        Args:
            item: DLQ item.
        Returns:
            The response model.
        """
        return cls(**vars(item))


class DlqRetryRequest(BaseModel):
    """Jobs to move back to the inbound queue; omit to move all."""

    r2_keys: list[str] | None = Field(default=None, max_length=100)
