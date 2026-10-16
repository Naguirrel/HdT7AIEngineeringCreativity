"""Construye los servicios compartidos y el contexto inicial para cualquier arquitectura."""

from src.agents.common.context import ParachuteContext, SharedServices
from src.config import AppConfig, DROP_ZONE_LATITUDE, DROP_ZONE_LONGITUDE, MAX_FORECAST_HORIZON_DAYS, OPEN_METEO_FORECAST_URL
from src.integrations.open_meteo import OpenMeteoClient
from src.services.calendar_service import InMemoryCalendarService
from src.services.faq_service import FaqService
from src.services.weather_service import WeatherService


def build_shared_services(config: AppConfig) -> SharedServices:
    open_meteo_client = OpenMeteoClient(
        latitude=DROP_ZONE_LATITUDE,
        longitude=DROP_ZONE_LONGITUDE,
        base_url=OPEN_METEO_FORECAST_URL,
    )
    weather_service = WeatherService(client=open_meteo_client, max_horizon_days=MAX_FORECAST_HORIZON_DAYS)
    calendar_service = InMemoryCalendarService()
    faq_service = FaqService.from_path(config.faq_path)
    return SharedServices(
        weather_service=weather_service,
        calendar_service=calendar_service,
        faq_service=faq_service,
    )


def build_context(config: AppConfig, architecture: str = "unknown") -> ParachuteContext:
    return ParachuteContext(services=build_shared_services(config), architecture=architecture)
