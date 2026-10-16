"""Authoritative business state and tools, served exclusively over Streamable HTTP."""

import argparse
import functools
import os
import secrets
import time
import threading
from datetime import date
from pathlib import Path

from mcp.server import MCPServer
import uvicorn

from src.agents.common.bootstrap import build_shared_services
from src.agents.common.booking_completion import (
    complete_pending_booking, compose_booking_answer, finish_turn,
)
from src.agents.common.context import ParachuteContext
from src.config import AppConfig, DEFAULT_FAQ_PATH
from src.observability import configure_logging, log_event
from src.tools.calendar_tools import book_appointment, evaluate_availability
from src.tools.faq_tools import answer_from_faq
from src.tools.weather_tools import evaluate_jump_day


class LoggedContext(ParachuteContext):
    def record_tool_event(self, tool, arguments, result, status):
        super().record_tool_event(tool, arguments, result, status)
        # Includes business calls made by finish_turn/complete_pending_booking,
        # not only direct MCP requests. Never include arguments or personal data.
        log_event(protocol="mcp", tool=tool, event="business_execution", status=status)


class SessionStore:
    """Separate conversation state, one shared calendar, bounded session lifetime.

    Tools are synchronous and protected by a shared reentrant lock. Run one
    worker so every conversation sees the same in-memory calendar.
    """

    def __init__(self, services, *, today=None, ttl=3600, limit=128):
        self.services, self.today = services, today
        self.ttl, self.limit = ttl, limit
        self.sessions = {}
        self.lock = threading.RLock()

    def prune(self):
        now = time.monotonic()
        for key, (_, touched) in list(self.sessions.items()):
            if now - touched > self.ttl:
                del self.sessions[key]

    def create(self):
        self.prune()
        if len(self.sessions) >= self.limit:
            raise ValueError("Limite de sesiones alcanzado; intenta mas tarde.")
        key = secrets.token_urlsafe(32)
        context = LoggedContext(services=self.services, architecture="mcp")
        if self.today:
            context.today = self.today
        self.sessions[key] = (context, time.monotonic())
        return key

    def get(self, key):
        self.prune()
        if key not in self.sessions:
            raise ValueError("Sesion MCP desconocida o vencida; inicia otra conversacion.")
        context, _ = self.sessions[key]
        self.sessions[key] = (context, time.monotonic())
        return context


def create_server(store):
    server = MCPServer("Parachute business tools")

    def logged(fn):
        @functools.wraps(fn)
        def invoke(*args, **kwargs):
            started = time.monotonic()
            log_event(protocol="mcp", tool=fn.__name__, event="start")
            try:
                with store.lock:
                    result = fn(*args, **kwargs)
            except Exception as error:
                log_event(protocol="mcp", tool=fn.__name__, event="error", error_type=type(error).__name__)
                # Never allow SDK error responses to expose input values or provider details.
                raise ValueError("No se pudo ejecutar la herramienta MCP.") from None
            log_event(protocol="mcp", tool=fn.__name__, event="complete",
                      duration_ms=round((time.monotonic() - started) * 1000))
            return result
        return invoke

    @server.tool()
    @logged
    def open_conversation() -> str:
        """Create an opaque business session; never expose its identifier to the model."""
        return store.create()

    @server.tool()
    @logged
    def close_conversation(session_id: str) -> str:
        """Release conversation state. Appointments stay in the shared calendar."""
        store.sessions.pop(session_id, None)
        return "closed"

    @server.tool()
    @logged
    def begin_turn(session_id: str, message: str) -> str:
        """Observe the original user message before any model or specialist invocation."""
        if not message.strip() or len(message) > 16000:
            raise ValueError("Mensaje vacio o demasiado largo.")
        store.get(session_id).observe_user_message(message)
        return "ready"

    @server.tool()
    @logged
    def search_faq(session_id: str, query: str) -> str:
        """Search official Parachute FAQs."""
        return answer_from_faq(store.get(session_id), query)

    @server.tool()
    @logged
    def check_jump_day(session_id: str, date_str: str) -> str:
        """Validate YYYY-MM-DD and assess jump weather using the existing safety policy."""
        return evaluate_jump_day(store.get(session_id), date_str)

    @server.tool()
    @logged
    def check_appointment_availability(session_id: str, date_str: str, party_size: int | None = None) -> str:
        """Check group capacity after approved weather and tandem acceptance if needed."""
        return evaluate_availability(store.get(session_id), date_str, party_size)

    @server.tool()
    @logged
    def create_appointment(session_id: str, date_str: str, customer_name: str = "",
                           contact: str = "", is_experienced_tandem: bool = False,
                           party_size: int | None = None) -> str:
        """Create an appointment only after ordered weather and capacity checks."""
        return book_appointment(store.get(session_id), date_str, customer_name, contact,
                                is_experienced_tandem, party_size)

    @server.tool()
    @logged
    def complete_booking(session_id: str) -> str:
        """Run the existing scheduling completion hook on authoritative server state."""
        context = store.get(session_id)
        if complete_pending_booking(context):
            return compose_booking_answer(context)
        return ""

    @server.tool()
    @logged
    def finalize_turn(session_id: str, model_output: str) -> str:
        """Apply existing booking, truthfulness and FAQ grounding guarantees."""
        return finish_turn(store.get(session_id), model_output)

    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--demo", action="store_true", help="Explicit fixed weather/date fixtures; no real weather")
    args = parser.parse_args()
    configure_logging()
    # This process needs the corpus and weather, never LLM credentials.
    config = AppConfig(llm_api_key="", llm_base_url="", llm_model="",
                       faq_path=Path(os.getenv("FAQ_PATH", str(DEFAULT_FAQ_PATH))))
    services = build_shared_services(config)
    today = None
    if args.demo:
        from evals.fixtures.weather import make_weather_service
        services.weather_service = make_weather_service("ideal")
        today = lambda: date(2026, 9, 17)
        log_event(protocol="mcp", mode="DEMO_FIXTURES", fixed_today="2026-09-17")
    server = create_server(SessionStore(services, today=today))
    log_event(protocol="mcp", event="starting", transport="streamable-http", port=args.port)
    uvicorn.run(server.streamable_http_app(), host="127.0.0.1", port=args.port, workers=1)


if __name__ == "__main__":
    main()
