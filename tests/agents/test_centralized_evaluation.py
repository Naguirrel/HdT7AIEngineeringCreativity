"""The programmatic runner preserves turns and isolates each scenario."""

import asyncio
from datetime import date
from types import SimpleNamespace

import pytest
from agents import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from src.agents.centralized.evaluation import run_centralized_session_async
from src.agents.common.context import ParachuteContext, SharedServices
from src.config import DEFAULT_FAQ_PATH
from src.services.calendar_service import InMemoryCalendarService
from src.services.faq_service import FaqService


def _build():
    agent = SimpleNamespace(name="Central Supervisor")
    context = ParachuteContext(
        services=SharedServices(
            weather_service=object(),
            calendar_service=InMemoryCalendarService(),
            faq_service=FaqService.from_path(DEFAULT_FAQ_PATH),
        ),
        architecture="centralized",
    )
    return agent, context


@pytest.mark.asyncio
async def test_programmatic_runner_keeps_turn_history_and_isolates_cases():
    histories = []

    async def fake_run(agent, history, *, context):
        histories.append([item.copy() for item in history])
        context.record_tool_event("search_faq", {}, {"match_count": 0}, "success")
        return SimpleNamespace(
            final_output=f"respuesta {len(histories)}",
            last_agent=agent,
            to_input_list=lambda: history + [{"role": "assistant", "content": "respuesta"}],
        )

    first = await run_centralized_session_async(
        ["hola", "otra pregunta"], build=_build, run=fake_run, fixed_today=date(2026, 9, 17)
    )
    second = await run_centralized_session_async(["hola"], build=_build, run=fake_run)
    assert first.answer == "respuesta 2"
    assert len(first.tool_calls) == 2
    assert len(second.tool_calls) == 1
    assert histories[1][0]["content"] == "hola"
    assert histories[1][-1]["content"] == "otra pregunta"
    assert histories[2] == [{"role": "user", "content": "hola"}]
    assert first.latency_ms >= 0


@pytest.mark.asyncio
async def test_programmatic_runner_rejects_empty_output():
    client = AsyncOpenAI(api_key="test-key", base_url="https://example.invalid/v1")

    def build_with_client():
        agent, context = _build()
        agent.model = OpenAIChatCompletionsModel(model="test-model", openai_client=client)
        return agent, context

    async def fake_run(agent, history, *, context):
        return SimpleNamespace(final_output="", last_agent=agent)

    with pytest.raises(RuntimeError, match="vacia"):
        await run_centralized_session_async(["hola"], build=build_with_client, run=fake_run)
    assert client.is_closed()


@pytest.mark.asyncio
async def test_promptfoo_provider_uses_only_answer_as_output(monkeypatch):
    from evals import provider
    from src.agents.centralized.evaluation import EvaluationResult

    async def fake_session(turns, **kwargs):
        return EvaluationResult("respuesta", [{"tool": "search_faq"}], [], 25)

    monkeypatch.setattr(provider, "run_centralized_session_async", fake_session)
    response = await provider.call_api("ignored", {}, {"vars": {"turns": ["consulta"], "scenario": "faq"}})
    assert response["output"] == "respuesta"
    assert response["metadata"]["tool_calls"][0]["tool"] == "search_faq"
    assert response["latencyMs"] == 25


@pytest.mark.asyncio
async def test_promptfoo_provider_handles_invalid_turns():
    from evals.provider import call_api

    assert "error" in await call_api("", {}, {"vars": {"turns": 42}})


def test_promptfoo_provider_survives_repeated_asyncio_run_like_the_real_worker(monkeypatch):
    """Promptfoo 0.123.1 persistent_wrapper calls asyncio.run(call_api(...)) for every case,
    so each case runs on a brand-new event loop; clients must be created and closed per case."""
    from evals import provider

    clients, loops = [], []

    def build_with_client():
        agent, context = _build()
        client = AsyncOpenAI(api_key="test-key", base_url="https://example.invalid/v1")
        agent.model = OpenAIChatCompletionsModel(model="test-model", openai_client=client)
        clients.append(client)
        return agent, context

    async def fake_run(agent, history, *, context):
        loops.append(asyncio.get_running_loop())
        assert not clients[-1].is_closed()
        return SimpleNamespace(
            final_output="respuesta",
            last_agent=agent,
            to_input_list=lambda: history + [{"role": "assistant", "content": "respuesta"}],
        )

    async def session(turns, **kwargs):
        return await run_centralized_session_async(turns, build=build_with_client, run=fake_run, **kwargs)

    monkeypatch.setattr(provider, "run_centralized_session_async", session)
    for _ in range(3):
        response = asyncio.run(provider.call_api("consulta", {}, {"vars": {"scenario": "faq", "turns": ["consulta"]}}))
        assert response["output"] == "respuesta"
        assert response["metadata"]["tool_calls"] == []
        assert clients[-1].is_closed()
    assert len(clients) == 3
    assert len({id(loop) for loop in loops}) == 3  # one fresh loop per case, as in the real worker
    assert all(loop.is_closed() for loop in loops)
