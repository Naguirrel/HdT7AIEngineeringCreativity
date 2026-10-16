"""Keyed pseudonyms, PII-free metadata, no SDK trace export and sanitized errors (AUD-015/016/023)."""

from datetime import timedelta
import hashlib
import json
from types import SimpleNamespace

import pytest
import requests

from src.agents.centralized.evaluation import run_centralized_session_async
from src.integrations.open_meteo import OpenMeteoClient, OpenMeteoError
from src.observability import GENERIC_USER_ERROR, user_facing_error
from src.services.weather_service import WeatherService
from src.tools.calendar_tools import book_appointment, evaluate_availability
from src.tools.weather_tools import evaluate_jump_day
from tests.agents.conftest import FIXED_TODAY, make_snapshot

DAY = FIXED_TODAY + timedelta(days=3)
NAME, CONTACT = "Ana Ejemplo", "5555-1234"


def _book(context):
    evaluate_jump_day(context, DAY.isoformat())
    evaluate_availability(context, DAY.isoformat())
    book_appointment(context, DAY.isoformat(), NAME, CONTACT)
    return context.get_tool_trace()[-1]["arguments"]


def test_pseudonyms_are_keyed_per_session_and_not_static_hashes(build_context):
    first = _book(build_context({DAY: make_snapshot(DAY)}))
    second = _book(build_context({DAY: make_snapshot(DAY)}))
    assert first["contact_hmac"] != second["contact_hmac"]  # cannot be compared across runs
    assert first["customer_name_hmac"] != second["customer_name_hmac"]
    static = {hashlib.sha256(value.encode()).hexdigest() for value in (NAME, CONTACT, "+50255551234")}
    assert not static & {first["contact_hmac"], first["customer_name_hmac"]}
    assert "contact_sha256" not in first and "customer_name_sha256" not in first


@pytest.mark.asyncio
async def test_exported_metadata_has_no_pii_or_pseudonyms_and_identity_is_checked_in_process(build_context):
    context = build_context({DAY: make_snapshot(DAY)})
    agent = SimpleNamespace(name="Central Supervisor")

    async def fake_run(agent, history, *, context):
        _book(context)
        return SimpleNamespace(final_output="ok", last_agent=agent, to_input_list=lambda: history)

    result = await run_centralized_session_async(
        [f"Reserva el {DAY.isoformat()}"], build=lambda: (agent, context), run=fake_run,
        expected_identity={"customer_name": "ana   ejemplo", "contact": "+502 5555 1234"},
    )
    exported = json.dumps(result.tool_calls) + result.answer
    for secret in (NAME, CONTACT, "55551234", "_hmac", "_sha256"):
        assert secret not in exported
    assert result.identity_checks == {"customer_name": True, "contact": True}

    mismatch = await run_centralized_session_async(
        ["otra"], build=lambda: (agent, build_context({DAY: make_snapshot(DAY)})), run=fake_run,
        expected_identity={"contact": "otro@example.com"},
    )
    assert mismatch.identity_checks == {"contact": False}


@pytest.mark.asyncio
async def test_sdk_trace_export_is_disabled_in_evaluation_even_with_openai_key(build_context, monkeypatch):
    from agents import set_tracing_disabled
    from agents.tracing import get_trace_provider

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    set_tracing_disabled(False)
    context = build_context({})
    agent = SimpleNamespace(name="Central Supervisor")

    async def fake_run(agent, history, *, context):
        assert get_trace_provider()._disabled is True
        return SimpleNamespace(final_output="Hola", last_agent=agent, to_input_list=lambda: history)

    await run_centralized_session_async(["Hola"], build=lambda: (agent, context), run=fake_run)
    assert get_trace_provider()._disabled is True


def test_open_meteo_errors_do_not_leak_http_body(requests_mock):
    url = "https://api.open-meteo.com/v1/forecast"
    requests_mock.get(url, status_code=500, text="internal secret-body token=abc")
    client = OpenMeteoClient(latitude=1.0, longitude=1.0, base_url=url)
    with pytest.raises(OpenMeteoError) as raised:
        client.get_weather(DAY)
    assert "secret-body" not in str(raised.value) and "500" in str(raised.value)
    requests_mock.get(url, exc=requests.exceptions.ConnectTimeout("connect to host:443 with key=abc"))
    with pytest.raises(OpenMeteoError) as raised:
        client.get_weather(DAY)
    assert "key=abc" not in str(raised.value)


def test_weather_tool_message_is_generic_on_provider_failure(build_context):
    class Leaky:
        def get_weather(self, requested_date):
            raise OpenMeteoError("upstream said: api_key=XYZ")

    context = build_context({})
    context.services.weather_service = WeatherService(Leaky(), max_horizon_days=15)
    message = evaluate_jump_day(context, DAY.isoformat())
    assert "XYZ" not in message and "pronostico" in message


def test_user_facing_errors_are_generic():
    message = user_facing_error(RuntimeError("Bearer sk-live-123 at https://api.groq.com stack..."))
    assert message == GENERIC_USER_ERROR
    assert "sk-live" not in message and "groq" not in message
