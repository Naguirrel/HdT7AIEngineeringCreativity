"""A2A 0.3 JSON-RPC wrapper around Parachute's central multi-agent system."""

import argparse
import asyncio
import time
from dataclasses import dataclass, field

import uvicorn
from dotenv import load_dotenv
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, Message, Part, TextPart
from uuid import uuid4

from src.agents.common.model_client import build_model
from src.config import load_config
from src.observability import configure_logging, log_event, GENERIC_USER_ERROR
from src.protocols.remote_system import Conversation


def agent_card(url):
    return AgentCard(
        name="Parachute S.A.", description="Sistema multiagente de informacion, clima y citas de salto.",
        url=url, version="1.0.0", default_input_modes=["text/plain"], default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        skills=[
            AgentSkill(id="faq", name="Informacion oficial", description="Responde desde las FAQ oficiales.",
                       tags=["faq"], examples=["¿Cual es el limite de peso?"]),
            AgentSkill(id="weather", name="Clima y seguridad", description="Evalua una fecha y las condiciones de salto.",
                       tags=["clima", "seguridad"], examples=["¿Se puede saltar el 2026-10-20?"]),
            AgentSkill(id="booking", name="Reservas", description="Valida clima y cupo antes de crear citas.",
                       tags=["citas"], examples=["Quiero reservar un salto."]),
        ],
    )


@dataclass
class Entry:
    conversation: Conversation = field(default_factory=Conversation)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    touched: float = field(default_factory=time.monotonic)


class ParachuteExecutor(AgentExecutor):
    def __init__(self, model, mcp_url):
        self.model, self.mcp_url = model, mcp_url
        self.sessions = {}

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        text = context.get_user_input().strip()
        # RequestContext supplies a context ID even for a client's first message.
        key = context.context_id or str(uuid4())
        now = time.monotonic()
        for old, entry in list(self.sessions.items()):
            if now - entry.touched > 1800 and not entry.lock.locked():
                del self.sessions[old]
        if not text or len(text) > 16000:
            answer = "Escribe un mensaje de entre 1 y 16000 caracteres."
        elif key not in self.sessions and len(self.sessions) >= 128:
            answer = "Limite de conversaciones alcanzado; intenta mas tarde."
        else:
            entry = self.sessions.setdefault(key, Entry())
            log_event(protocol="a2a", event="request_received")
            async with entry.lock:
                try:
                    answer = await entry.conversation.turn(text, mcp_url=self.mcp_url, model=self.model)
                except Exception as error:
                    log_event(protocol="a2a", event="request_error", error_type=type(error).__name__)
                    answer = GENERIC_USER_ERROR
                finally:
                    entry.touched = time.monotonic()
            log_event(protocol="a2a", event="response_ready")
        await event_queue.enqueue_event(Message(
            role="agent", message_id=str(uuid4()), context_id=key,
            parts=[Part(root=TextPart(text=answer))],
        ))

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        from a2a.types import TaskNotCancelableError
        from a2a.utils.errors import ServerError
        raise ServerError(error=TaskNotCancelableError())


def create_app(model, mcp_url="http://127.0.0.1:8001/mcp", url="http://127.0.0.1:8000/"):
    handler = DefaultRequestHandler(
        agent_executor=ParachuteExecutor(model, mcp_url), task_store=InMemoryTaskStore(),
    )
    return A2AStarletteApplication(agent_card=agent_card(url), http_handler=handler).build()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--mcp-url", default="http://127.0.0.1:8001/mcp")
    args = parser.parse_args()
    configure_logging()
    load_dotenv(override=False)
    try:
        model = build_model(load_config())
    except ValueError as error:
        parser.error(str(error))
    log_event(protocol="a2a", event="starting", port=args.port)
    uvicorn.run(create_app(model, args.mcp_url, f"http://127.0.0.1:{args.port}/"),
                host="127.0.0.1", port=args.port, workers=1)


if __name__ == "__main__":
    main()
