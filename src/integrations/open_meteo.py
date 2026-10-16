"""Cliente unico para Open-Meteo. No contiene reglas de seguridad."""

from dataclasses import dataclass
from datetime import date

import requests

from src.domain.weather_models import WeatherSnapshot
from src.domain.clock import GUATEMALA_TIMEZONE_NAME

DAILY_VARIABLES = [
    "wind_gusts_10m_max",
    "temperature_2m_max",
    "precipitation_sum",
    "cloud_cover_mean",
    "wind_speed_10m_max",
]
# Units requested below; a response in other units must not be interpreted silently.
EXPECTED_UNITS = {
    "wind_gusts_10m_max": {"km/h"},
    "wind_speed_10m_max": {"km/h"},
    "precipitation_sum": {"mm"},
    "cloud_cover_mean": {"%"},
    "temperature_2m_max": {"°C", "C"},
}


class OpenMeteoError(RuntimeError):
    """Fallo al construir, ejecutar o interpretar la solicitud a Open-Meteo."""


@dataclass(frozen=True)
class OpenMeteoClient:
    latitude: float
    longitude: float
    base_url: str
    timeout_seconds: float = 10.0

    def get_weather(self, requested_date: date) -> WeatherSnapshot:
        """Obtiene el pronostico diario para `requested_date` y lo mapea al modelo interno."""
        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "daily": ",".join(DAILY_VARIABLES),
            "timezone": GUATEMALA_TIMEZONE_NAME,
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
            "temperature_unit": "celsius",
            "start_date": requested_date.isoformat(),
            "end_date": requested_date.isoformat(),
        }

        # Error messages never include the HTTP body, URL or exception text: they may reach the
        # model and the user. The exception chain keeps the detail for local debugging only.
        try:
            response = requests.get(self.base_url, params=params, timeout=self.timeout_seconds)
        except requests.RequestException as error:
            raise OpenMeteoError(f"Fallo de red al consultar Open-Meteo ({type(error).__name__}).") from error

        if response.status_code != 200:
            raise OpenMeteoError(f"Open-Meteo respondio con estado HTTP {response.status_code}.")

        try:
            payload = response.json()
        except ValueError as error:
            raise OpenMeteoError("Open-Meteo devolvio un cuerpo que no es JSON valido.") from error

        return self._map_response(payload, requested_date)

    def _map_response(self, payload: dict, requested_date: date) -> WeatherSnapshot:
        daily = payload.get("daily")
        if not isinstance(daily, dict):
            raise OpenMeteoError("La respuesta de Open-Meteo no incluye la seccion 'daily'.")

        dates = daily.get("time")
        if not isinstance(dates, list) or not dates or requested_date.isoformat() not in dates:
            raise OpenMeteoError(
                f"Open-Meteo no devolvio pronostico para la fecha solicitada {requested_date.isoformat()}."
            )
        index = dates.index(requested_date.isoformat())

        units = payload.get("daily_units")
        if units is not None:
            if not isinstance(units, dict):
                raise OpenMeteoError("La respuesta de Open-Meteo tiene unidades invalidas.")
            for variable, expected in EXPECTED_UNITS.items():
                if variable in units and units[variable] not in expected:
                    raise OpenMeteoError(f"Open-Meteo devolvio {variable} en una unidad inesperada.")

        values = {}
        for variable in DAILY_VARIABLES:
            series = daily.get(variable)
            if not isinstance(series, list) or len(series) != len(dates):
                raise OpenMeteoError("La respuesta de Open-Meteo tiene una estructura incompleta.")
            values[variable] = series[index]

        if any(value is None for value in values.values()):
            raise OpenMeteoError(f"Open-Meteo devolvio datos incompletos para {requested_date.isoformat()}.")

        try:
            return WeatherSnapshot(
                date=requested_date,
                wind_speed_10m_kmh=values["wind_speed_10m_max"],
                wind_gust_10m_kmh=values["wind_gusts_10m_max"],
                precipitation_mm=values["precipitation_sum"],
                cloud_cover_percent=values["cloud_cover_mean"],
                temperature_2m_c=values["temperature_2m_max"],
                source="open-meteo",
            )
        except ValueError as error:
            # NaN, infinity, negative or non-numeric values are rejected, never treated as IDEAL.
            raise OpenMeteoError(f"Open-Meteo devolvio datos invalidos para {requested_date.isoformat()}.") from error
