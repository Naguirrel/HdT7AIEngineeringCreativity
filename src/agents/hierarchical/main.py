"""Arquitectura jerarquica: Root Manager -> Knowledge/Booking Manager -> especialistas.

Dos niveles reales de coordinacion: el Root Manager nunca llama directamente a
un especialista, siempre delega en el manager de dominio correspondiente.
"""

import sys

from agents import Agent, Model

from src.agents.common.bootstrap import build_context
from src.agents.common.booking_completion import booking_result_or_continue
from src.agents.common.cli import run_chat
from src.agents.common.context import ParachuteContext
from src.agents.common.model_client import build_model
from src.agents.common.policies import (
    BOOKING_RULES, ENTRY_AGENT_RULES, GROUNDING_RULES, TRUTHFUL_OUTPUT_RULES, compose,
)
from src.agents.common.specialist_agents import build_faq_agent, build_scheduling_agent, build_weather_agent
from src.config import ConfigError, load_config
from src.observability import configure_logging

ROOT_INSTRUCTIONS = compose(
    """Eres el Root Manager de Parachute S.A. No resuelves hechos ni citas tu mismo:
decides si la peticion corresponde a knowledge_manager (preguntas frecuentes) o a
booking_manager (fecha, clima y citas), y puedes usar ambos si el usuario pide
varias cosas a la vez. En saludos, despedidas o preguntas fuera del dominio no
delegues.""",
    ENTRY_AGENT_RULES,
)

KNOWLEDGE_MANAGER_INSTRUCTIONS = compose(
    """Eres el Knowledge Manager de Parachute S.A. Delegas toda pregunta de
conocimiento en faq_specialist y devuelves su respuesta. Esta capa existe para poder
agregar mas fuentes de conocimiento en el futuro sin cambiar al Root Manager.""",
    GROUNDING_RULES,
)

BOOKING_MANAGER_INSTRUCTIONS = compose(
    """Eres el Booking Manager de Parachute S.A. Coordinas el flujo completo de
reserva: primero usa weather_specialist para validar la fecha y evaluar si se puede
saltar; solo si el resultado no es PROHIBITED continuas con scheduling_specialist
para comprobar el cupo y crear la cita.""",
    BOOKING_RULES,
    TRUTHFUL_OUTPUT_RULES,
)


def build_root_manager(model: Model | None = None) -> tuple[Agent, ParachuteContext]:
    config = load_config()
    context = build_context(config, architecture="hierarchical")
    model = model or build_model(config)

    faq_agent = build_faq_agent(model)
    weather_agent = build_weather_agent(model)
    scheduling_agent = build_scheduling_agent(model)

    knowledge_manager = Agent(
        name="Knowledge Manager",
        instructions=KNOWLEDGE_MANAGER_INSTRUCTIONS,
        model=model,
        tools=[
            faq_agent.as_tool(
                tool_name="faq_specialist",
                tool_description="Responde preguntas frecuentes sobre el evento de paracaidismo.",
            ),
        ],
    )

    booking_manager = Agent(
        name="Booking Manager",
        instructions=BOOKING_MANAGER_INSTRUCTIONS,
        model=model,
        tool_use_behavior=booking_result_or_continue,
        tools=[
            weather_agent.as_tool(
                tool_name="weather_specialist",
                tool_description="Valida una fecha y evalua si las condiciones permiten saltar.",
            ),
            scheduling_agent.as_tool(
                tool_name="scheduling_specialist",
                tool_description="Verifica disponibilidad y crea la cita de salto.",
            ),
        ],
    )

    root_manager = Agent(
        name="Root Manager",
        instructions=ROOT_INSTRUCTIONS,
        model=model,
        tool_use_behavior=booking_result_or_continue,
        tools=[
            knowledge_manager.as_tool(
                tool_name="knowledge_manager",
                tool_description="Coordina preguntas frecuentes / de conocimiento.",
            ),
            booking_manager.as_tool(
                tool_name="booking_manager",
                tool_description="Coordina la validacion de clima y la creacion de citas.",
            ),
        ],
    )
    return root_manager, context


def main() -> int:
    configure_logging()
    try:
        root_manager, context = build_root_manager()
    except ConfigError as error:
        print(f"Error de configuracion: {error}", file=sys.stderr)
        return 2

    run_chat(root_manager, context, "jerarquica")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
