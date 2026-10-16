"""Modelos tipados para clima y evaluacion de seguridad del salto."""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
import math


class Decision(str, Enum):
    IDEAL = "IDEAL"
    MARGINAL = "MARGINAL"
    PROHIBITED = "PROHIBITED"


def _finite_number(name: str, value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} debe ser un numero finito.")
    return float(value)


@dataclass(frozen=True)
class WeatherSnapshot:
    date: date
    wind_speed_10m_kmh: float
    wind_gust_10m_kmh: float
    precipitation_mm: float
    cloud_cover_percent: float
    temperature_2m_c: float
    source: str = "open-meteo"

    def __post_init__(self) -> None:
        """Invalid data must never reach the policy, where NaN would compare as IDEAL."""
        if type(self.date) is not date:
            raise ValueError("La fecha del pronostico debe ser una fecha valida.")
        for name in ("wind_speed_10m_kmh", "wind_gust_10m_kmh", "precipitation_mm", "cloud_cover_percent"):
            value = _finite_number(name, getattr(self, name))
            if value < 0:
                raise ValueError(f"{name} no puede ser negativo.")
            object.__setattr__(self, name, value)
        if self.cloud_cover_percent > 100:
            raise ValueError("cloud_cover_percent no puede superar 100.")
        object.__setattr__(self, "temperature_2m_c", _finite_number("temperature_2m_c", self.temperature_2m_c))


@dataclass(frozen=True)
class JumpAssessment:
    decision: Decision
    reasons: list[str] = field(default_factory=list)
    weather: WeatherSnapshot | None = None

    @property
    def requires_experienced_tandem(self) -> bool:
        return self.decision == Decision.MARGINAL

    @property
    def allows_appointment(self) -> bool:
        return self.decision != Decision.PROHIBITED
