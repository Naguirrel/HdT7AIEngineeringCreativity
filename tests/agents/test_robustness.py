"""Provider error classification, real-path smoke test and strict weather data (AUD-020/021/024/025)."""

from datetime import date, datetime, timezone
import json
from types import SimpleNamespace

from agents.exceptions import MaxTurnsExceeded, ModelBehaviorError
import openai
import pydantic
import pytest

from evals import provider
from src.agents.common.grounding import DOMAIN_ABSTENTION
from src.domain.weather_models import Decision, WeatherSnapshot
from src.domain.weather_policy import assess_jump_conditions
from src.integrations.open_meteo import OpenMeteoClient, OpenMeteoError

DAY = date(2026, 9, 20)
URL = "https://api.open-meteo.com/v1/forecast"


def _bare(error_type):
    return error_type.__new__(error_type)  # provider SDK errors need request objects otherwise


def _pydantic_error():
    class Model(pydantic.BaseModel):
        value: int
    try:
        Model(value="x")
    except pydantic.ValidationError as error:
        return error


@pytest.mark.asyncio
@pytest.mark.parametrize(("error", "prefix"), [
    (_bare(openai.RateLimitError), "Proveedor LLM: RateLimitError"),
    (_bare(openai.APIConnectionError), "Proveedor LLM: APIConnectionError"),
    (json.JSONDecodeError("bad", "{", 0), "Respuesta invalida del modelo: JSONDecodeError"),
    (_pydantic_error(), "Respuesta invalida del modelo: ValidationError"),
    (ModelBehaviorError("tool json"), "Agente: ModelBehaviorError"),
    (MaxTurnsExceeded("too many"), "Agente: MaxTurnsExceeded"),
    (ValueError("internal detail token=abc"), "Fallo durante la ejecucion: ValueError"),
    (RuntimeError("secret"), "Fallo durante la ejecucion: RuntimeError"),
])
async def test_provider_classifies_errors_without_echoing_details(monkeypatch, error, prefix):
    async def failing(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(provider, "run_centralized_session_async", failing)
    response = await provider.call_api("x", {}, {"vars": {"turns": ["hola"]}})
    assert response == {"error": prefix}


@pytest.mark.asyncio
@pytest.mark.parametrize(("variables", "prefix"), [
    ({"turns": 42}, "Escenario invalido"),
    ({"turns": ["  "]}, "Escenario invalido"),
    ({"turns": ["hola"], "fixed_today": "17/09/2026"}, "Escenario invalido"),
    ({"turns": ["hola"], "weather_fixture": "missing"}, "Fixture invalido"),
    ({"turns": ["hola"], "calendar_fixture": "missing"}, "Fixture invalido"),
])
async def test_provider_reports_scenario_and_fixture_errors_before_running(monkeypatch, variables, prefix):
    async def must_not_run(*_args, **_kwargs):
        raise AssertionError("the agent must not run for an invalid scenario")

    monkeypatch.setattr(provider, "run_centralized_session_async", must_not_run)
    response = await provider.call_api("", {}, {"vars": variables})
    assert response["error"].startswith(prefix)


def test_smoke_script_uses_the_guatemala_date():
    from scripts.smoke_test import build_script

    script = build_script(date(2026, 9, 17))
    assert "2026-09-20" in script[1] and "2027-04-05" in script[2]


@pytest.mark.asyncio
async def test_smoke_run_uses_finish_turn_and_closes_clients(build_context):
    from openai import AsyncOpenAI

    from scripts.smoke_test import close_model_client, run_architecture

    context = build_context({})
    agent = SimpleNamespace(name="Central Supervisor")

    async def fake_run(agent, history, *, context):
        return SimpleNamespace(final_output="Bobby Fischer ganó.", last_agent=agent, to_input_list=lambda: history)

    lines = await run_architecture("centralized", agent, context, ["¿Quién ganó?"], run=fake_run)
    assert lines[2] == f"[Central Supervisor]: {DOMAIN_ABSTENTION}"

    client = AsyncOpenAI(api_key="test-key", base_url="https://example.invalid/v1")
    await close_model_client(SimpleNamespace(model=SimpleNamespace(_client=client)))
    assert client.is_closed()


def test_clock_used_by_smoke_is_guatemala_time():
    from src.domain.clock import current_guatemala_date

    assert current_guatemala_date(datetime(2026, 9, 18, 3, 0, tzinfo=timezone.utc)) == date(2026, 9, 17)


@pytest.mark.parametrize("overrides", [
    {"wind_speed_10m_kmh": float("nan")},
    {"wind_gust_10m_kmh": float("inf")},
    {"precipitation_mm": -0.1},
    {"cloud_cover_percent": 100.5},
    {"cloud_cover_percent": -1},
    {"temperature_2m_c": float("nan")},
    {"wind_speed_10m_kmh": "10"},
    {"wind_speed_10m_kmh": True},
    {"date": "2026-09-20"},
])
def test_invalid_weather_snapshots_are_rejected(overrides):
    values = dict(date=DAY, wind_speed_10m_kmh=10.0, wind_gust_10m_kmh=10.0, precipitation_mm=0.0,
                  cloud_cover_percent=10.0, temperature_2m_c=25.0)
    values.update(overrides)
    with pytest.raises(ValueError):
        WeatherSnapshot(**values)


def test_valid_extremes_still_classify_correctly():
    weather = WeatherSnapshot(DAY, 0, 0, 0, 100, -5)
    assert assess_jump_conditions(weather).decision == Decision.PROHIBITED


def _payload(**overrides):
    daily = {
        "time": [DAY.isoformat()],
        "wind_speed_10m_max": [15.0], "wind_gusts_10m_max": [20.0], "precipitation_sum": [0.0],
        "cloud_cover_mean": [40.0], "temperature_2m_max": [27.5],
    }
    daily.update(overrides.pop("daily", {}))
    return {"daily": daily, **overrides}


@pytest.mark.parametrize("payload", [
    _payload(daily={"wind_speed_10m_max": [float("nan")]}),
    _payload(daily={"precipitation_sum": [-1.0]}),
    _payload(daily={"cloud_cover_mean": [150.0]}),
    _payload(daily={"wind_gusts_10m_max": ["fuerte"]}),
    _payload(daily={"time": []}),
    _payload(daily={"wind_speed_10m_max": []}),
    _payload(daily={"time": [DAY.isoformat(), "2026-09-21"]}),
    _payload(daily_units={"wind_speed_10m_max": "mph"}),
    _payload(daily_units={"precipitation_sum": "inch"}),
    _payload(daily_units="km/h"),
])
def test_invalid_open_meteo_payloads_are_errors_not_ideal(requests_mock, payload):
    requests_mock.get(URL, text=json.dumps(payload, allow_nan=True))
    with pytest.raises(OpenMeteoError):
        OpenMeteoClient(latitude=1.0, longitude=1.0, base_url=URL).get_weather(DAY)


def test_expected_units_are_accepted(requests_mock):
    units = {"wind_speed_10m_max": "km/h", "wind_gusts_10m_max": "km/h", "precipitation_sum": "mm",
             "cloud_cover_mean": "%", "temperature_2m_max": "°C"}
    requests_mock.get(URL, json=_payload(daily_units=units))
    snapshot = OpenMeteoClient(latitude=1.0, longitude=1.0, base_url=URL).get_weather(DAY)
    assert snapshot.cloud_cover_percent == 40.0
