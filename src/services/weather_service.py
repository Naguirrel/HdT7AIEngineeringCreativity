"""Servicio de aplicacion: valida fecha, consulta Open-Meteo y evalua condiciones."""

from dataclasses import dataclass
from datetime import date

from src.domain.date_policy import validate_forecast_date
from src.domain.weather_models import JumpAssessment
from src.domain.weather_policy import assess_jump_conditions
from src.integrations.open_meteo import OpenMeteoClient, OpenMeteoError
from src.observability import log_event


class WeatherServiceError(RuntimeError):
    """Error de negocio al obtener/evaluar el clima de una fecha."""


@dataclass(frozen=True)
class WeatherService:
    client: OpenMeteoClient
    max_horizon_days: int

    def check_jump_day(self, requested_date: date, today: date) -> JumpAssessment:
        """Valida la fecha, obtiene el pronostico y devuelve la evaluacion deterministica.

        Este es el unico camino que las tres arquitecturas deben usar para evaluar un dia:
        valida -> Open-Meteo -> evaluacion, siempre en el mismo orden.
        """
        validation = validate_forecast_date(requested_date, today, self.max_horizon_days)
        if not validation.is_valid:
            raise WeatherServiceError(validation.message)

        try:
            weather = self.client.get_weather(requested_date)
        except OpenMeteoError as error:
            log_event(component="weather_service", weather_check_result="provider_error", error_type=type(error).__name__)
            raise WeatherServiceError(
                "No fue posible obtener el pronostico meteorologico en este momento. Intenta mas tarde."
            ) from error

        return assess_jump_conditions(weather)
