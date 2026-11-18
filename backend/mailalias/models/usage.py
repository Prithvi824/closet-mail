"""Daily per-user usage counters for the activity chart and quotas."""

# 1st party imports
import uuid
from datetime import date

# 3rd party imports
from sqlalchemy import BigInteger, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

# local imports
from mailalias.models.base import Base, Timestamps, UUIDPrimaryKey


class UsageDaily(UUIDPrimaryKey, Timestamps, Base):
    """Mail counts by outcome, replies and bytes for one subdomain on one UTC day."""

    __tablename__ = "usage_daily"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_usage_daily_user_day"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    day: Mapped[date]
    received: Mapped[int] = mapped_column(default=0)
    # forwards counts delivered forwards; the other outcomes have their own counters.
    forwards: Mapped[int] = mapped_column(default=0)
    quarantined: Mapped[int] = mapped_column(default=0)
    blocked: Mapped[int] = mapped_column(default=0)
    discarded: Mapped[int] = mapped_column(default=0)
    replies: Mapped[int] = mapped_column(default=0)
    bytes: Mapped[int] = mapped_column(BigInteger, default=0)
