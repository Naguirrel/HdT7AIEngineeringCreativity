"""Validacion pura del horizonte de pronostico disponible."""

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class DateValidationResult:
    is_valid: bool
    message: str | None = None


def validate_forecast_date(
    requested_date: date,
    today: date,
    max_horizon_days: int,
) -> DateValidationResult:
    """Valida que `requested_date` este dentro de [today, today + max_horizon_days].

    Open-Meteo ofrece hasta 16 dias de pronostico: hoy (dia 0) mas `max_horizon_days`
    dias adicionales, por lo que el ultimo dia permitido es today + max_horizon_days.
    """
    if requested_date < today:
        return DateValidationResult(
            is_valid=False,
            message=f"La fecha {requested_date.isoformat()} ya paso. Elige hoy o una fecha futura.",
        )

    last_valid_date = today + timedelta(days=max_horizon_days)
    if requested_date > last_valid_date:
        return DateValidationResult(
            is_valid=False,
            message=(
                f"La fecha {requested_date.isoformat()} esta fuera del horizonte de pronostico. "
                f"El ultimo dia disponible es {last_valid_date.isoformat()}."
            ),
        )

    return DateValidationResult(is_valid=True)
