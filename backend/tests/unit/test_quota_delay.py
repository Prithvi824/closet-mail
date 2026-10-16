"""Retry delay for mail held by the global daily send cap."""

# 1st party imports
from datetime import UTC, datetime

# 3rd party imports
import pytest

# local imports
from mailalias.services.quota import MAX_RETRY_DELAY_SECONDS, cap_retry_delay


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 16, 23, 0, tzinfo=UTC), 3_600 + 60),
        (datetime(2026, 10, 16, 20, 30, tzinfo=UTC), 3 * 3_600 + 1_800 + 60),
        (datetime(2026, 10, 16, 1, 0, tzinfo=UTC), MAX_RETRY_DELAY_SECONDS),
    ],
)
def test_cap_retry_waits_for_utc_midnight(now: datetime, expected: int) -> None:
    """The delay lands just after the reset, never beyond the queue's maximum.

    Args:
        now: Current time.
        expected: Expected delay in seconds.
    Returns:
        None.
    """
    assert cap_retry_delay(now) == expected
