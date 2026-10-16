"""Booking authorization and final output across nested agents."""

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from agents import RunContextWrapper, Runner
from agents.tool_context import ToolContext

from src.agents.centralized.evaluation import run_centralized_session_async
from src.agents.centralized.main import build_supervisor
from src.agents.common.booking_completion import booking_result_or_continue, finish_turn
from src.tools.calendar_tools import book_appointment, check_appointment_availability, create_appointment, evaluate_availability
from src.tools.weather_tools import check_jump_day, evaluate_jump_day
from tests.agents.conftest import FIXED_TODAY, make_snapshot


DAY = FIXED_TODAY + timedelta(days=1)


def _book(context):
    evaluate_jump_day(context, DAY.isoformat())
    evaluate_availability(context, DAY.isoformat())
    return book_appointment(context, DAY.isoformat(), "Ana Lopez", "ana@example.invalid")


def test_sdk_completion_uses_successful_tool_state_not_specialist_text(build_context):
    context = build_context({DAY: make_snapshot(DAY)})
    wrapper = RunContextWrapper(context=context)
    nested = SimpleNamespace(tool=SimpleNamespace(name="scheduling_specialist"), output="No.")
    assert not booking_result_or_continue(wrapper, [nested]).is_final_output

    confirmation = _book(context)
    result = booking_result_or_continue(wrapper, [nested])
    assert result.is_final_output
    assert result.final_output == confirmation
    assert DAY.isoformat() in result.final_output
    assert finish_turn(context, "No.") == confirmation

    context.observe_user_message("Otra pregunta")
    assert not booking_result_or_continue(wrapper, [nested]).is_final_output
    assert finish_turn(context, "Otra respuesta") == "Otra respuesta"


@pytest.mark.asyncio
async def test_nested_specialists_and_business_tools_share_one_context(monkeypatch, build_context):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    supervisor, context = build_supervisor()
    fixture = build_context({DAY: make_snapshot(DAY)})
    context.services.weather_service = fixture.services.weather_service
    context.today = fixture.today
    shared_context = context

    async def invoke(tool, arguments):
        raw = json.dumps(arguments)
        wrapper = ToolContext(
            context=shared_context, tool_name=tool.name,
            tool_call_id=f"test-{tool.name}", tool_arguments=raw,
        )
        return await tool.on_invoke_tool(wrapper, raw)

    async def fake_run(*, starting_agent, input, context, **kwargs):
        assert context.context is shared_context
        if starting_agent.name == "Weather Agent":
            output = await invoke(check_jump_day, {"date_str": DAY.isoformat()})
        else:
            await invoke(check_appointment_availability, {"date_str": DAY.isoformat()})
            output = await invoke(create_appointment, {
                "date_str": DAY.isoformat(), "customer_name": "Ana Lopez",
                "contact": "ana@example.invalid", "party_size": 1,
                "is_experienced_tandem": False,
            })
        return SimpleNamespace(final_output=output)

    monkeypatch.setattr(Runner, "run", fake_run)
    tools = {tool.name: tool for tool in supervisor.tools}
    try:
        await invoke(tools["weather_specialist"], {"input": "Evalua la fecha"})
        output = await invoke(tools["scheduling_specialist"], {"input": "Reserva"})
        assert output == context.appointment_confirmation
        assert [event["tool"] for event in context.get_tool_trace()] == [
            "check_jump_day", "check_appointment_availability", "create_appointment"
        ]
        assert context.get_tool_trace()[-1]["result"]["created"] is True
    finally:
        await supervisor.model._client.close()


@pytest.mark.asyncio
async def test_programmatic_answer_cannot_replace_success_with_no(build_context):
    context = build_context({DAY: make_snapshot(DAY)})
    agent = SimpleNamespace(name="Central Supervisor")

    async def fake_run(agent, history, *, context):
        _book(context)
        return SimpleNamespace(
            final_output="No.", last_agent=agent,
            to_input_list=lambda: history + [{"role": "assistant", "content": "No."}],
        )

    result = await run_centralized_session_async(
        [f"Reserva el {DAY.isoformat()}"], build=lambda: (agent, context), run=fake_run
    )
    assert "Cita confirmada" in result.answer
    assert DAY.isoformat() in result.answer
    assert result.answer != "No."
