"""Request/response models for the operator console (health, DLQ)."""

# 1st party imports
from datetime import datetime
from typing import Any

# 3rd party imports
from pydantic import BaseModel, Field

# local imports
from mailalias.services.operator import DlqItem, Health


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
