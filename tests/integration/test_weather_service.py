from dataclasses import dataclass
from datetime import date, timedelta

import pytest

from src.domain.weather_models import Decision, WeatherSnapshot
from src.integrations.open_meteo import OpenMeteoError
from src.services.weather_service import WeatherService, WeatherServiceError

TODAY = date(2026, 9, 17)
HORIZON = 15


@dataclass
class FakeOpenMeteoClient:
    snapshot: WeatherSnapshot | None = None
    error: Exception | None = None
    requested_dates: list[date] | None = None

    def __post_init__(self):
        if self.requested_dates is None:
            self.requested_dates = []

    def get_weather(self, requested_date: date) -> WeatherSnapshot:
        self.requested_dates.append(requested_date)
        if self.error is not None:
            raise self.error
        return self.snapshot


def make_snapshot(target_date: date) -> WeatherSnapshot:
    return WeatherSnapshot(
        date=target_date,
        wind_speed_10m_kmh=10.0,
        wind_gust_10m_kmh=10.0,
        precipitation_mm=0.0,
        cloud_cover_percent=10.0,
        temperature_2m_c=25.0,
    )


def test_check_jump_day_returns_assessment_for_valid_date():
    target = TODAY + timedelta(days=1)
    client = FakeOpenMeteoClient(snapshot=make_snapshot(target))
    service = WeatherService(client=client, max_horizon_days=HORIZON)

    assessment = service.check_jump_day(target, TODAY)

    assert assessment.decision == Decision.IDEAL
    assert client.requested_dates == [target]


def test_check_jump_day_rejects_past_date_without_calling_open_meteo():
    client = FakeOpenMeteoClient(snapshot=make_snapshot(TODAY))
    service = WeatherService(client=client, max_horizon_days=HORIZON)
    past = TODAY - timedelta(days=1)

    with pytest.raises(WeatherServiceError):
        service.check_jump_day(past, TODAY)

    assert client.requested_dates == []


def test_check_jump_day_rejects_date_outside_horizon_without_calling_open_meteo():
    client = FakeOpenMeteoClient(snapshot=make_snapshot(TODAY))
    service = WeatherService(client=client, max_horizon_days=HORIZON)
    too_far = TODAY + timedelta(days=HORIZON + 1)

    with pytest.raises(WeatherServiceError):
        service.check_jump_day(too_far, TODAY)

    assert client.requested_dates == []


def test_check_jump_day_wraps_open_meteo_errors():
    client = FakeOpenMeteoClient(error=OpenMeteoError("boom"))
    service = WeatherService(client=client, max_horizon_days=HORIZON)

    with pytest.raises(WeatherServiceError):
        service.check_jump_day(TODAY, TODAY)
