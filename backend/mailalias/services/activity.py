"""Per-user activity: daily forward/reply totals and the most recent handled messages."""

# 1st party imports
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

# 3rd party imports
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.models import Alias, MailLog, UsageDaily, User

RECENT_LIMIT = 100


@dataclass(frozen=True)
class DailyTotals:
    """One calendar day (UTC) of usage."""

    day: date
    forwards: int
    replies: int
    bytes: int


async def daily_totals(db: AsyncSession, user: User, days: int) -> list[DailyTotals]:
    """Usage for the last `days` days including today, oldest first, zero-filled.

    Args:
        db: Session.
        user: Owner.
        days: Window length.
    Returns:
        One entry per day.
    """
    today = datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    rows = await db.scalars(
        select(UsageDaily).where(UsageDaily.user_id == user.id, UsageDaily.day >= start)
    )
    by_day = {row.day: row for row in rows}
    totals = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        row = by_day.get(day)
        totals.append(
            DailyTotals(day, row.forwards, row.replies, row.bytes)
            if row
            else DailyTotals(day, 0, 0, 0)
        )
    return totals


async def recent_mail(db: AsyncSession, user: User) -> list[tuple[MailLog, str | None]]:
    """The latest handled messages with their alias address (no correspondents or subjects).

    Args:
        db: Session.
        user: Owner.
    Returns:
        (log row, alias address) pairs, newest first.
    """
    query = (
        select(MailLog, Alias.address)
        .outerjoin(Alias, Alias.id == MailLog.alias_id)
        .where(MailLog.user_id == user.id)
        .order_by(MailLog.created_at.desc())
        .limit(RECENT_LIMIT)
    )
    return [(log, address) for log, address in (await db.execute(query)).all()]
