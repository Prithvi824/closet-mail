"""Response model for the activity page (totals and recent mail, without personal data)."""

# 1st party imports
import uuid
from datetime import date, datetime

# 3rd party imports
from pydantic import BaseModel

# local imports
from mailalias.mail.types import MailKind, Outcome
from mailalias.models import MailLog
from mailalias.services.activity import DailyTotals


class DailyActivity(BaseModel):
    """Totals for one day."""

    day: date
    forwards: int
    replies: int
    bytes: int


class RecentMail(BaseModel):
    """One handled message: what happened, never who or what it said."""

    id: uuid.UUID
    created_at: datetime
    kind: MailKind
    outcome: Outcome
    reason: str | None
    alias_id: uuid.UUID | None
    alias_address: str | None
    spam_score: float | None
    size_bytes: int


class ActivityResponse(BaseModel):
    """Daily totals (oldest first) and the latest messages (newest first)."""

    daily: list[DailyActivity]
    recent: list[RecentMail]

    @classmethod
    def build(
        cls, daily: list[DailyTotals], recent: list[tuple[MailLog, str | None]]
    ) -> "ActivityResponse":
        """Build from service results.

        Args:
            daily: Zero-filled totals.
            recent: (log, alias address) pairs.
        Returns:
            The response model.
        """
        return cls(
            daily=[DailyActivity(**vars(day)) for day in daily],
            recent=[
                RecentMail(
                    id=log.id,
                    created_at=log.created_at,
                    kind=log.kind,
                    outcome=log.outcome,
                    reason=log.reason,
                    alias_id=log.alias_id,
                    alias_address=address,
                    spam_score=log.spam_score,
                    size_bytes=log.size_bytes,
                )
                for log, address in recent
            ],
        )
