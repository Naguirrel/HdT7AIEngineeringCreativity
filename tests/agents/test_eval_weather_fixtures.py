from datetime import date

import pytest

from evals.fixtures.weather import FixtureError, make_weather_service
from src.agents.common.context import ParachuteContext, SharedServices
from src.domain.weather_models import Decision
from src.services.calendar_service import InMemoryCalendarService
from src.tools.weather_tools import evaluate_jump_day

TODAY = date(2026, 9, 17)
VALID_DATE = date(2026, 9, 20)


@pytest.mark.parametrize(
    ("fixture", "decision", "value"),
    [
        ("ideal", Decision.IDEAL, 10),
        ("marginal_wind_lower", Decision.MARGINAL, 20),
        ("marginal_wind_upper", Decision.MARGINAL, 28),
        ("prohibited_wind", Decision.PROHIBITED, 28.1),
        ("prohibited_gusts", Decision.PROHIBITED, 10),
        ("prohibited_rain", Decision.PROHIBITED, 10),
        ("marginal_clouds", Decision.MARGINAL, 10),
        ("prohibited_clouds", Decision.PROHIBITED, 10),
    ],
)
def test_fixture_values_and_boundaries(fixture, decision, value):
    service = make_weather_service(fixture)
    assessment = service.check_jump_day(VALID_DATE, TODAY)
    assert assessment.decision == decision
    assert assessment.weather.wind_speed_10m_kmh == value
    assert assessment.weather.source == "fixture"
    assert service.client.calls == [VALID_DATE]


def test_fixture_error_and_unknown_name():
    from src.services.weather_service import WeatherServiceError

    with pytest.raises(FixtureError):
        make_weather_service("missing")
    with pytest.raises(WeatherServiceError, match="No fue posible obtener el pronostico") as raised:
        make_weather_service("error").check_jump_day(VALID_DATE, TODAY)
    assert "simulado" in str(raised.value.__cause__)  # detail kept only in the exception chain


def test_clock_horizon_and_no_network_for_invalid_date():
    from src.services.weather_service import WeatherServiceError

    service = make_weather_service("ideal")
    assert service.check_jump_day(date(2026, 10, 2), TODAY).decision == Decision.IDEAL
    with pytest.raises(WeatherServiceError, match="horizonte"):
        service.check_jump_day(date(2026, 10, 3), TODAY)
    assert service.client.calls == [date(2026, 10, 2)]


def test_new_failed_assessment_clears_previous_one():
    service = make_weather_service("ideal")
    context = ParachuteContext(
        services=SharedServices(service, InMemoryCalendarService(), None),
        today=lambda: TODAY,
    )
    evaluate_jump_day(context, "2026-09-20")
    assert context.jump_assessment is not None
    evaluate_jump_day(context, "2026-10-03")
    assert context.jump_assessment is None
    assert context.requested_date is None
    assert service.client.calls == [VALID_DATE]


def test_each_service_has_independent_call_history():
    first = make_weather_service("ideal")
    second = make_weather_service("ideal")
    first.check_jump_day(VALID_DATE, TODAY)
    assert second.client.calls == []


def test_calendar_fixtures_preload_participants_and_reject_unknown_names():
    from evals.fixtures.calendar import make_calendar_service

    assert make_calendar_service("empty").booked_participants(VALID_DATE) == 0
    full = make_calendar_service("full_2026_09_20")
    assert full.booked_participants(VALID_DATE) == 8
    assert full.check_availability(VALID_DATE, 1) is False
    assert make_calendar_service("nearly_full_2026_09_20").check_availability(VALID_DATE, 1) is True
    assert make_calendar_service("full_2026_09_20") is not full  # fresh calendar per case
    with pytest.raises(FixtureError):
        make_calendar_service("missing")


@pytest.mark.asyncio
async def test_provider_uses_the_requested_calendar_fixture(monkeypatch):
    from evals import provider
    from src.agents.centralized.evaluation import EvaluationResult

    seen = {}

    async def fake_session(turns, **kwargs):
        seen["calendar"] = kwargs["calendar_service"]
        return EvaluationResult("respuesta", [], [], 1)

    monkeypatch.setattr(provider, "run_centralized_session_async", fake_session)
    response = await provider.call_api("x", {}, {"vars": {"turns": ["hola"], "calendar_fixture": "full_2026_09_20"}})
    assert response["metadata"]["calendar_fixture"] == "full_2026_09_20"
    assert seen["calendar"].booked_participants(VALID_DATE) == 8
    error = await provider.call_api("x", {}, {"vars": {"turns": ["hola"], "calendar_fixture": "nope"}})
    assert "error" in error
