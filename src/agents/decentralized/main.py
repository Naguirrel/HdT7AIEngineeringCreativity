"""Arquitectura descentralizada: sin supervisor global, los agentes se transfieren
el control entre si mediante handoffs.

FAQ Agent <-> Weather Agent -> Scheduling Agent -> FAQ Agent

El Scheduling Agent nunca recibe un handoff directo desde el usuario sin pasar
antes por Weather Agent, y sus tools (src/tools/calendar_tools.py) verifican de
forma estructural que exista una evaluacion valida en el contexto antes de
poder crear una cita, sin importar por que ruta de handoffs se llego ahi.
"""

import sys

from agents import Agent, Model, RunContextWrapper, handoff
from pydantic import BaseModel

from src.agents.common.bootstrap import build_context
from src.agents.common.booking_completion import booking_result_or_continue
from src.agents.common.cli import run_chat
from src.agents.common.context import ParachuteContext
from src.agents.common.model_client import build_model
from src.agents.common.policies import BOOKING_RULES, ENTRY_AGENT_RULES, TRUTHFUL_OUTPUT_RULES, compose
from src.agents.common.specialist_agents import (
    FAQ_INSTRUCTIONS,
    SCHEDULING_INSTRUCTIONS,
    WEATHER_INSTRUCTIONS,
)
from src.config import ConfigError, load_config
from src.observability import configure_logging, log_event
from src.tools.calendar_tools import check_appointment_availability, create_appointment
from src.tools.faq_tools import search_faq
from src.tools.weather_tools import check_jump_day


class HandoffReason(BaseModel):
    """Motivo breve de la transferencia. Groq rechaza tools con un JSON schema de
    parametros vacio (bug conocido de su validador), asi que cada handoff exige
    este campo minimo en vez de un input vacio; de paso queda una razon logueable."""

    reason: str


def _log_handoff_reason(wrapper: RunContextWrapper[ParachuteContext], data: HandoffReason) -> None:
    log_event(architecture=wrapper.context.architecture, handoff_reason_present=bool(data.reason))

# The FAQ Agent is the entry point here, so it carries the same entry rules as the
# centralized supervisor and the hierarchical Root Manager.
FAQ_DECENTRALIZED_INSTRUCTIONS = compose(
    FAQ_INSTRUCTIONS,
    "Si detectas intencion de reservar una cita o de conocer el clima de un dia, "
    "transfiere la conversacion al Weather Agent.",
    ENTRY_AGENT_RULES,
)
WEATHER_DECENTRALIZED_INSTRUCTIONS = compose(
    WEATHER_INSTRUCTIONS,
    "Si el resultado no es PROHIBITED y el usuario quiere continuar con la reserva, "
    "transfiere la conversacion al Scheduling Agent. Si es PROHIBITED, responde tu mismo "
    "sin transferir a creacion de citas.",
    BOOKING_RULES,
    TRUTHFUL_OUTPUT_RULES,
)
SCHEDULING_DECENTRALIZED_INSTRUCTIONS = compose(
    SCHEDULING_INSTRUCTIONS,
    "Si durante la conversacion aparece una pregunta de conocimiento no relacionada con "
    "la cita, transfiere de vuelta al FAQ Agent.",
    BOOKING_RULES,
    TRUTHFUL_OUTPUT_RULES,
)


def build_decentralized_agents(model) -> tuple[Agent, Agent, Agent]:
    faq_agent = Agent(
        name="FAQ Agent",
        handoff_description="Responde preguntas frecuentes sobre el evento de paracaidismo.",
        instructions=FAQ_DECENTRALIZED_INSTRUCTIONS,
        tools=[search_faq],
        model=model,
    )
    weather_agent = Agent(
        name="Weather Agent",
        handoff_description="Valida la fecha y evalua deterministicamente si se puede saltar.",
        instructions=WEATHER_DECENTRALIZED_INSTRUCTIONS,
        tools=[check_jump_day],
        model=model,
    )
    scheduling_agent = Agent(
        name="Scheduling Agent",
        handoff_description="Verifica disponibilidad y crea la cita de salto.",
        instructions=SCHEDULING_DECENTRALIZED_INSTRUCTIONS,
        tools=[check_appointment_availability, create_appointment],
        tool_use_behavior=booking_result_or_continue,
        model=model,
    )

    def _handoff(target: Agent) -> object:
        return handoff(target, on_handoff=_log_handoff_reason, input_type=HandoffReason)

    faq_agent.handoffs = [_handoff(weather_agent)]
    weather_agent.handoffs = [_handoff(faq_agent), _handoff(scheduling_agent)]
    scheduling_agent.handoffs = [_handoff(faq_agent)]

    return faq_agent, weather_agent, scheduling_agent


def build_entry_agent(model: Model | None = None) -> tuple[Agent, ParachuteContext]:
    config = load_config()
    context = build_context(config, architecture="decentralized")
    model = model or build_model(config)

    faq_agent, _weather_agent, _scheduling_agent = build_decentralized_agents(model)
    return faq_agent, context


def main() -> int:
    configure_logging()
    try:
        entry_agent, context = build_entry_agent()
    except ConfigError as error:
        print(f"Error de configuracion: {error}", file=sys.stderr)
        return 2

    run_chat(entry_agent, context, "descentralizada")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
