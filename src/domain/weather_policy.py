"""Politica deterministica de seguridad para el salto (no depende del LLM)."""

from .weather_models import Decision, JumpAssessment, WeatherSnapshot

_DECISION_RANK = {Decision.IDEAL: 0, Decision.MARGINAL: 1, Decision.PROHIBITED: 2}


def _worst(current: Decision, candidate: Decision) -> Decision:
    return candidate if _DECISION_RANK[candidate] > _DECISION_RANK[current] else current


def _assess_wind(speed: float) -> tuple[Decision, str | None]:
    if speed > 28:
        return Decision.PROHIBITED, f"Viento en superficie de {speed} km/h supera el limite de 28 km/h."
    if speed >= 20:
        return Decision.MARGINAL, f"Viento en superficie de {speed} km/h esta en rango marginal (20-28 km/h): solo tandem experimentado."
    return Decision.IDEAL, None


def _assess_gust(gust: float) -> tuple[Decision, str | None]:
    if gust > 35:
        return Decision.PROHIBITED, f"Rafagas de {gust} km/h superan el limite de 35 km/h."
    return Decision.IDEAL, None


def _assess_precipitation(precipitation: float) -> tuple[Decision, str | None]:
    if precipitation > 0.0:
        return Decision.PROHIBITED, f"Precipitacion de {precipitation} mm detectada; se requiere 0.0 mm."
    return Decision.IDEAL, None


def _assess_clouds(cloud_cover: float) -> tuple[Decision, str | None]:
    if cloud_cover > 75:
        return Decision.PROHIBITED, f"Cobertura de nubes de {cloud_cover}% supera el limite de 75%."
    if cloud_cover >= 30:
        return Decision.MARGINAL, f"Cobertura de nubes de {cloud_cover}% esta en rango marginal (30-75%)."
    return Decision.IDEAL, None


def assess_jump_conditions(weather: WeatherSnapshot) -> JumpAssessment:
    """Aplica la politica de 'peor condicion prevalece' sobre las cuatro variables criticas."""
    decision = Decision.IDEAL
    reasons: list[str] = []

    for assess in (
        lambda: _assess_wind(weather.wind_speed_10m_kmh),
        lambda: _assess_gust(weather.wind_gust_10m_kmh),
        lambda: _assess_precipitation(weather.precipitation_mm),
        lambda: _assess_clouds(weather.cloud_cover_percent),
    ):
        result, reason = assess()
        decision = _worst(decision, result)
        if reason:
            reasons.append(reason)

    return JumpAssessment(decision=decision, reasons=reasons, weather=weather)
