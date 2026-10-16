from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from src.agents.common.context import ParachuteContext, SharedServices
from src.domain.weather_models import WeatherSnapshot
from src.services.calendar_service import InMemoryCalendarService
from src.services.faq_service import FaqService
from src.services.weather_service import WeatherService

FAQ_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "FAQs_Parachute_SA_Guatemala_2026.txt"
FIXED_TODAY = date(2026, 9, 17)


@dataclass
class FakeOpenMeteoClient:
    snapshot_by_date: dict[date, WeatherSnapshot]

    def get_weather(self, requested_date: date) -> WeatherSnapshot:
        return self.snapshot_by_date[requested_date]


def make_snapshot(target_date: date, **overrides) -> WeatherSnapshot:
    values = dict(
        date=target_date,
        wind_speed_10m_kmh=10.0,
        wind_gust_10m_kmh=10.0,
        precipitation_mm=0.0,
        cloud_cover_percent=10.0,
        temperature_2m_c=25.0,
    )
    values.update(overrides)
    return WeatherSnapshot(**values)


@pytest.fixture
def build_context():
    def _build(snapshots: dict[date, WeatherSnapshot]) -> ParachuteContext:
        weather_service = WeatherService(
            client=FakeOpenMeteoClient(snapshot_by_date=snapshots),
            max_horizon_days=15,
        )
        services = SharedServices(
            weather_service=weather_service,
            calendar_service=InMemoryCalendarService(),
            faq_service=FaqService.from_path(FAQ_PATH),
        )
        return ParachuteContext(services=services, today=lambda: FIXED_TODAY)

    return _build
