import json
from datetime import timedelta

from tests.agents.conftest import FIXED_TODAY, make_snapshot

from src.integrations.open_meteo import OpenMeteoError
from src.services.weather_service import WeatherService
from src.tools.calendar_tools import book_appointment, evaluate_availability
from src.tools.faq_tools import answer_from_faq
from src.tools.weather_tools import evaluate_jump_day


DAY = FIXED_TODAY + timedelta(days=1)


def test_trace_records_order_arguments_and_results(build_context):
    context = build_context({DAY: make_snapshot(DAY)})
    evaluate_jump_day(context, DAY.isoformat())
    evaluate_availability(context, DAY.isoformat())
    book_appointment(context, DAY.isoformat(), "Ana Lopez", "ana@example.com")

    trace = context.get_tool_trace()
    assert [event["sequence"] for event in trace] == [1, 2, 3]
    assert [event["tool"] for event in trace] == [
        "check_jump_day", "check_appointment_availability", "create_appointment"
    ]
    assert [event["status"] for event in trace] == ["success"] * 3
    assert trace[0]["arguments"] == {"date_str": DAY.isoformat()}
    assert trace[0]["result"]["decision"] == "IDEAL"
    assert trace[1]["result"] == {"available": True}
    assert trace[2]["arguments"]["customer_name_provided"] is True
    assert trace[2]["arguments"]["contact_provided"] is True
    assert trace[2]["arguments"]["customer_name_hmac"] == context.pseudonymize("Ana Lopez")
    assert trace[2]["arguments"]["contact_hmac"] == context.pseudonymize("ana@example.com")
    assert trace[2]["result"]["created"] is True
    assert "Ana Lopez" not in json.dumps(trace)
    assert "ana@example.com" not in json.dumps(trace)


def test_trace_records_controlled_errors_and_no_uninvoked_tools(build_context):
    context = build_context({})
    evaluate_jump_day(context, "invalid-date")
    evaluate_availability(context, "invalid-date")
    book_appointment(context, DAY.isoformat(), "Ana Lopez", "ana@example.com")
    trace = context.get_tool_trace()
    assert [event["tool"] for event in trace] == [
        "check_jump_day", "check_appointment_availability", "create_appointment"
    ]
    assert all(event["status"] == "error" for event in trace)
    assert [event["result"]["error"] for event in trace] == [
        "invalid_date_format", "invalid_date_format", "no_assessment"
    ]
    assert all(event["arguments"].get("date_str") is None for event in trace[:2])
    assert "search_faq" not in [event["tool"] for event in trace]


def test_faq_trace_hides_query_and_sessions_are_isolated(build_context):
    first = build_context({})
    second = build_context({})
    secret = "fake-token-do-not-log"
    answer_from_faq(first, f"peso maximo {secret}")
    first_trace = first.get_tool_trace()
    assert first_trace[0]["tool"] == "search_faq"
    assert first_trace[0]["result"]["match_count"] >= 1
    assert first_trace[0]["arguments"]["query_length"] > 0
    assert first_trace[0]["arguments"]["query_hmac"] == first.pseudonymize(f"peso maximo {secret}")
    assert secret not in json.dumps(first_trace)
    assert second.get_tool_trace() == []
    first_trace[0]["result"]["match_count"] = 999
    assert first.get_tool_trace()[0]["result"]["match_count"] != 999


def test_weather_service_failure_is_recorded_without_leaking_error_detail(build_context):
    context = build_context({})

    class FailingClient:
        def get_weather(self, requested_date):
            raise OpenMeteoError("fake-secret-error-detail")

    context.services.weather_service = WeatherService(FailingClient(), max_horizon_days=15)
    assert "Error" in evaluate_jump_day(context, DAY.isoformat())
    trace = context.get_tool_trace()
    assert trace[0]["status"] == "error"
    assert trace[0]["result"] == {"error": "weather_check_failed"}
    assert "fake-secret-error-detail" not in json.dumps(trace)
