"""Real HTTP MCP + A2A tests with scripted models and fixed weather, no API keys."""

import asyncio
from contextlib import contextmanager
from datetime import date
import socket
import threading
import time

import pytest

pytest.importorskip("a2a", reason="Install requirements-protocols.txt for protocol tests")
import httpx
import uvicorn
from agents.mcp import MCPServerStreamableHttp
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory

from evals.fixtures.weather import make_weather_service
from src.agents.common.context import SharedServices
from src.config import DEFAULT_FAQ_PATH
from src.observability import configure_logging
from src.protocols.a2a_server import create_app
from src.protocols.mcp_server import SessionStore, create_server
from src.protocols.remote_system import Conversation, RemoteTools
from src.protocols.terminal import TerminalSession
from src.services.calendar_service import InMemoryCalendarService
from src.services.faq_service import FaqService
from tests.agents.scripted_model import ScriptedModel, sequence

DAY = "2026-09-20"
REQUEST = f"Reserva el {DAY} para Ana Ejemplo, ana@example.invalid, somos 2 personas."


@contextmanager
def live_server(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    try:
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("HTTP test server failed to start")
            time.sleep(.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive(), "HTTP test server failed to stop"


@pytest.fixture
def store():
    configure_logging()
    return SessionStore(SharedServices(
        weather_service=make_weather_service("ideal"),
        calendar_service=InMemoryCalendarService(),
        faq_service=FaqService.from_path(DEFAULT_FAQ_PATH),
    ), today=lambda: date(2026, 9, 17))


@pytest.fixture
def mcp_url(store):
    with live_server(create_server(store).streamable_http_app()) as base:
        yield base + "/mcp"


async def remote(server):
    result = await server.call_tool("open_conversation", {})
    key = next(part.text for part in result.content if part.type == "text")
    return RemoteTools(server, key)


def connection(url):
    return MCPServerStreamableHttp(name="test", params={"url": url}, client_session_timeout_seconds=30)


async def test_discovery_faq_and_session_isolation(mcp_url, store):
    async with connection(mcp_url) as server:
        assert {tool.name for tool in await server.list_tools()} >= {
            "search_faq", "check_jump_day", "check_appointment_availability", "create_appointment",
        }
        one, two = await remote(server), await remote(server)
        await one.call("begin_turn", message="¿Cual es el limite de peso?")
        assert "100 kg" in await one.call("search_faq", query="limite de peso")
        assert store.get(two.session_id).turn_faq_entries == []
        assert store.get(one.session_id).turn_tools == ["search_faq"]
        await one.call("close_conversation")
        with pytest.raises(ValueError):
            store.get(one.session_id)


async def test_ordering_and_confirmation_survive_http(mcp_url, store):
    async with connection(mcp_url) as server:
        tools = await remote(server)
        await tools.call("begin_turn", message=REQUEST)
        assert "primero" in await tools.call("create_appointment", date_str=DAY)
        assert "IDEAL" in await tools.call("check_jump_day", date_str=DAY)
        assert "primero" in await tools.call("create_appointment", date_str=DAY)
        assert "Hay cupo" in await tools.call("check_appointment_availability", date_str=DAY)
        answer = await tools.call("finalize_turn", model_output="Listo")
        assert answer.startswith("Cita confirmada") and "participantes: 2" in answer
        successful = [e["tool"] for e in store.get(tools.session_id).get_tool_trace() if e["status"] == "success"]
        assert successful == ["check_jump_day", "check_appointment_availability", "create_appointment"]


@pytest.mark.parametrize("weather", ["marginal_wind_upper", "prohibited_wind"])
async def test_unsafe_or_unconfirmed_weather_never_books(mcp_url, store, weather):
    store.services.weather_service = make_weather_service(weather)
    async with connection(mcp_url) as server:
        tools = await remote(server)
        await tools.call("begin_turn", message=REQUEST)
        await tools.call("check_jump_day", date_str=DAY)
        await tools.call("check_appointment_availability", date_str=DAY)
        answer = await tools.call("finalize_turn", model_output="Tu cita quedo confirmada.")
        assert "Cita confirmada" not in answer
        assert not store.get(tools.session_id).appointments
        if weather.startswith("marginal"):
            await tools.call("begin_turn", message=f"Acepto tandem experimentado para {DAY}.")
            answer = await tools.call("finalize_turn", model_output="Listo")
            assert answer.startswith("Cita confirmada")
            assert "tandem con instructor experimentado" in answer


async def test_combined_faq_and_booking_are_completed_remotely(mcp_url, store):
    async with connection(mcp_url) as server:
        tools = await remote(server)
        await tools.call("begin_turn", message=REQUEST + " y dime que ropa debo llevar.")
        await tools.call("check_jump_day", date_str=DAY)
        answer = await tools.call("finalize_turn", model_output="Listo")
        assert "Cita confirmada" in answer and "ropa cómoda y deportiva" in answer
        names = store.get(tools.session_id).turn_tools
        assert names == ["check_jump_day", "check_appointment_availability", "create_appointment", "search_faq"]


def faq_model():
    return ScriptedModel({
        "Eres el supervisor central": sequence(
            lambda user, _o: ("tool", "faq_specialist", {"input": user}),
            lambda _u, outputs: ("message", outputs[0]),
        ),
        "Eres el especialista en preguntas frecuentes": sequence(
            lambda user, _o: ("tool", "search_faq", {"query": user}),
        ),
    })


async def test_terminal_to_a2a_to_real_multiagent_to_mcp(mcp_url, store):
    with live_server(create_app(faq_model(), mcp_url)) as a2a_url:
        async with httpx.AsyncClient(timeout=30) as http:
            card = await A2ACardResolver(httpx_client=http, base_url=a2a_url).get_agent_card()
            assert {skill.id for skill in card.skills} == {"faq", "weather", "booking"}
            client = ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create(card)
            try:
                session = TerminalSession(client)
                assert "100 kg" in await session.ask("¿Cual es el limite de peso?")
                key = session.context_id
                assert key
                await session.ask("¿Que ropa debo llevar?")
                assert session.context_id == key
                assert len(store.sessions) == 1
                ctx = next(iter(store.sessions.values()))[0]
                assert len(ctx.user_messages) == 2
                assert [e["tool"] for e in ctx.get_tool_trace()] == ["search_faq", "search_faq"]
            finally:
                await client.close()


async def test_model_never_receives_session_identifier(mcp_url, store):
    model = faq_model()
    conversation = Conversation()
    await conversation.turn("¿Cual es el limite de peso?", mcp_url=mcp_url, model=model)
    assert conversation.session_id not in str(model.calls)
    assert conversation.session_id not in str(conversation.history)


async def test_mcp_error_does_not_become_grounded_model_output(mcp_url):
    async with connection(mcp_url) as server:
        with pytest.raises(RuntimeError):
            await RemoteTools(server, "unknown").call("search_faq", query="test")


def test_expiration_does_not_remove_shared_calendar(store, monkeypatch):
    key = store.create()
    store.sessions[key] = (store.get(key), 0)
    monkeypatch.setattr("src.protocols.mcp_server.time.monotonic", lambda: 4000)
    with pytest.raises(ValueError):
        store.get(key)
    assert store.services.calendar_service is not None


@pytest.mark.parametrize("weather", ["ideal", "marginal_wind_upper", "prohibited_wind"])
async def test_real_supervisor_books_only_when_weather_and_user_allow_it(mcp_url, store, weather):
    store.services.weather_service = make_weather_service(weather)
    def supervisor(user, outputs):
        if "cepto" in user:
            if not outputs:
                return ("tool", "scheduling_specialist", {"input": "Crea la cita del " + DAY})
            return ("message", outputs[-1])
        if not outputs:
            return ("tool", "weather_specialist", {"input": "Evalua " + DAY})
        if weather != "ideal":
            return ("message", outputs[0])
        if len(outputs) == 1:
            return ("tool", "scheduling_specialist", {"input": "Crea la cita del " + DAY})
        return ("message", outputs[-1])
    model = ScriptedModel({
        "Eres el supervisor central": supervisor,
        "Eres el especialista en clima": sequence(
            ("tool", "check_jump_day", {"date_str": DAY}),
            lambda _u, outputs: ("message", outputs[0]),
        ),
        "Eres el especialista en calendarizacion": sequence(
            ("tool", "check_appointment_availability", {"date_str": DAY}),
            ("tool", "create_appointment", {"date_str": DAY}),
            lambda _u, outputs: ("message", outputs[-1]),
        ),
    })
    conversation = Conversation()
    answer = await conversation.turn(REQUEST, mcp_url=mcp_url, model=model)
    ctx = store.get(conversation.session_id)
    if weather == "prohibited_wind":
        assert "PROHIBITED" in answer
        assert not ctx.appointments
        return
    if weather == "marginal_wind_upper":
        assert "MARGINAL" in answer and not ctx.appointments
        answer = await conversation.turn("Acepto tandem experimentado para " + DAY,
                                         mcp_url=mcp_url, model=model)
    assert answer.startswith("Cita confirmada")
    assert len(ctx.appointments) == 1
    assert ctx.appointments[0].data.party_size == 2
    assert [event["tool"] for event in ctx.get_tool_trace() if event["status"] == "success"][-3:] == [
        "check_jump_day", "check_appointment_availability", "create_appointment",
    ]
