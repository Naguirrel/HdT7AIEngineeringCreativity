"""Deterministic Open-Meteo replacement used by every Promptfoo scenario."""

import json
from datetime import date
from pathlib import Path

from src.config import MAX_FORECAST_HORIZON_DAYS
from src.domain.weather_models import WeatherSnapshot
from src.integrations.open_meteo import OpenMeteoError
from src.services.weather_service import WeatherService


class FixtureError(ValueError):
    pass


class FixedWeatherClient:
    def __init__(self, name: str):
        fixtures = json.loads(Path(__file__).with_name("weather.json").read_text(encoding="utf-8"))
        if name not in fixtures:
            raise FixtureError(f"Fixture meteorologico desconocido: {name}")
        self.name = name
        self.values = fixtures[name]
        self.calls: list[date] = []

    def get_weather(self, requested_date: date) -> WeatherSnapshot:
        self.calls.append(requested_date)
        if self.values is None:
            raise OpenMeteoError("Fallo simulado del servicio meteorologico")
        values = self.values
        return WeatherSnapshot(
            date=requested_date,
            wind_speed_10m_kmh=values["wind_speed"],
            wind_gust_10m_kmh=values["wind_gusts"],
            precipitation_mm=values["precipitation"],
            cloud_cover_percent=values["cloud_cover"],
            temperature_2m_c=values["temperature"],
            source="fixture",
        )


def make_weather_service(name: str) -> WeatherService:
    return WeatherService(client=FixedWeatherClient(name), max_horizon_days=MAX_FORECAST_HORIZON_DAYS)
