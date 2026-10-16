from datetime import date, datetime, timezone

import pytest

from src.domain.clock import GUATEMALA_TIMEZONE_NAME, current_guatemala_date


def test_guatemala_date_before_and_after_local_midnight():
    assert GUATEMALA_TIMEZONE_NAME == "America/Guatemala"
    assert current_guatemala_date(datetime(2026, 10, 1, 5, 59, tzinfo=timezone.utc)) == date(2026, 9, 30)
    assert current_guatemala_date(datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)) == date(2026, 10, 1)


def test_guatemala_date_rejects_naive_clock():
    with pytest.raises(ValueError):
        current_guatemala_date(datetime(2026, 10, 1, 6, 0))
