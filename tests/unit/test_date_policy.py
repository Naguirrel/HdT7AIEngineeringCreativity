from datetime import date, timedelta

import pytest

from src.domain.date_policy import validate_forecast_date

TODAY = date(2026, 9, 17)
HORIZON = 15


def test_today_is_valid():
    result = validate_forecast_date(TODAY, TODAY, HORIZON)
    assert result.is_valid


def test_tomorrow_is_valid():
    result = validate_forecast_date(TODAY + timedelta(days=1), TODAY, HORIZON)
    assert result.is_valid


def test_last_allowed_day_is_valid():
    result = validate_forecast_date(TODAY + timedelta(days=HORIZON), TODAY, HORIZON)
    assert result.is_valid


def test_first_day_outside_horizon_is_rejected():
    result = validate_forecast_date(TODAY + timedelta(days=HORIZON + 1), TODAY, HORIZON)
    assert not result.is_valid
    assert result.message is not None


def test_past_date_is_rejected():
    result = validate_forecast_date(TODAY - timedelta(days=1), TODAY, HORIZON)
    assert not result.is_valid


@pytest.mark.parametrize("offset", [-100, -1])
def test_various_past_dates_are_rejected(offset):
    result = validate_forecast_date(TODAY + timedelta(days=offset), TODAY, HORIZON)
    assert not result.is_valid


@pytest.mark.parametrize("offset", [HORIZON + 1, HORIZON + 30])
def test_various_dates_outside_horizon_are_rejected(offset):
    result = validate_forecast_date(TODAY + timedelta(days=offset), TODAY, HORIZON)
    assert not result.is_valid
