"""Tool compartido de clima/seguridad. Envuelve el unico camino: validar -> Open-Meteo -> evaluar.

La logica vive en `evaluate_jump_day`, una funcion plana testeable sin necesidad
de instanciar el runtime de agentes; el decorador @function_tool solo la conecta
al contexto de la conversacion.
"""

from agents import RunContextWrapper, function_tool

from src.agents.common.context import ParachuteContext, records_output
from src.domain.dates import normalized_date_or_none, parse_date_argument
from src.domain.weather_models import Decision
from src.observability import log_event
from src.services.weather_service import WeatherServiceError

def _format_assessment(assessment) -> str:
    weather = assessment.weather
    lines = [
        f"Fecha: {weather.date.isoformat()}",
        f"Decision: {assessment.decision.value}",
        f"Viento superficie: {weather.wind_speed_10m_kmh} km/h",
        f"Rafagas: {weather.wind_gust_10m_kmh} km/h",
        f"Precipitacion: {weather.precipitation_mm} mm",
        f"Cobertura de nubes: {weather.cloud_cover_percent}%",
        f"Temperatura: {weather.temperature_2m_c} C",
    ]
    if assessment.reasons:
        lines.append("Motivos: " + "; ".join(assessment.reasons))
    if assessment.decision == Decision.PROHIBITED:
        lines.append("No se puede crear una cita para este dia.")
    elif assessment.decision == Decision.MARGINAL:
        lines.append("Solo se permite salto tandem con instructor experimentado.")
    return "\n".join(lines)


@records_output
def evaluate_jump_day(context: ParachuteContext, date_str: str) -> str:
    """Logica del tool check_jump_day, invocable directamente en tests."""
    previous_date = context.requested_date
    previous_decision = context.jump_assessment.decision if context.jump_assessment else None
    previous_checked_on = context.assessment_checked_on
    previous_confirmation = context.confirmed_tandem_date
    # A failed new request must not leave an earlier day eligible for booking.
    # Created appointments are facts of the session and are not erased here.
    context.requested_date = None
    context.jump_assessment = None
    context.assessment_checked_on = None
    context.availability_approved_date = None
    context.confirmed_tandem_date = None
    trace_args = {"date_str": normalized_date_or_none(date_str)}
    log_event(architecture=context.architecture, tool="check_jump_day", requested_date=trace_args["date_str"])

    try:
        parsed_date = parse_date_argument(date_str)
    except ValueError as error:
        context.record_tool_event("check_jump_day", trace_args, {"error": "invalid_date_format"}, "error")
        return f"Fecha invalida: {error}"

    try:
        checked_on = context.today()
        assessment = context.services.weather_service.check_jump_day(parsed_date, checked_on)
    except WeatherServiceError as error:
        log_event(architecture=context.architecture, tool="check_jump_day", weather_check_result="error")
        context.record_tool_event("check_jump_day", trace_args, {"error": "weather_check_failed"}, "error")
        return f"Error: {error}"

    context.requested_date = parsed_date
    context.jump_assessment = assessment
    context.assessment_checked_on = checked_on
    # A same-day recheck that is still MARGINAL keeps the user's explicit tandem acceptance.
    if (
        previous_confirmation == parsed_date and previous_date == parsed_date
        and previous_checked_on == checked_on
        and previous_decision == Decision.MARGINAL and assessment.decision == Decision.MARGINAL
    ):
        context.confirmed_tandem_date = parsed_date
    log_event(
        architecture=context.architecture,
        tool="check_jump_day",
        weather_check_result="ok",
        jump_assessment=assessment.decision.value,
    )
    context.record_tool_event(
        "check_jump_day", trace_args,
        {"decision": assessment.decision.value, "date": parsed_date.isoformat()}, "success",
    )
    return _format_assessment(assessment)


@function_tool
def check_jump_day(wrapper: RunContextWrapper[ParachuteContext], date_str: str) -> str:
    """Valida la fecha, consulta Open-Meteo y evalua deterministicamente si se puede saltar.

    Args:
        date_str: fecha solicitada en formato YYYY-MM-DD.
    """
    return evaluate_jump_day(wrapper.context, date_str)
