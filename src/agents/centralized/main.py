"""Arquitectura centralizada: un unico supervisor que expone especialistas via as_tool()."""

import sys

from agents import Agent, Model

from src.agents.common.bootstrap import build_context
from src.agents.common.booking_completion import booking_result_or_continue
from src.agents.common.cli import run_chat
from src.agents.common.context import ParachuteContext
from src.agents.common.model_client import build_model
from src.agents.common.policies import ENTRY_AGENT_RULES, compose
from src.agents.common.specialist_agents import build_faq_agent, build_scheduling_agent, build_weather_agent
from src.config import ConfigError, load_config
from src.observability import configure_logging

SUPERVISOR_INSTRUCTIONS = compose(
    """Eres el supervisor central de Parachute S.A. Recibes toda interaccion del usuario
y decides que especialista usar:
- faq_specialist para preguntas frecuentes sobre el evento (FAQ oficiales);
- weather_specialist para validar una fecha y evaluar si se puede saltar (check_jump_day);
- scheduling_specialist para comprobar cupo y crear la cita
  (check_appointment_availability y create_appointment).
Puedes combinar especialistas si el usuario pide varias cosas a la vez. En saludos,
despedidas o preguntas fuera del dominio no invoques ningun especialista.""",
    ENTRY_AGENT_RULES,
)


def build_supervisor(model: Model | None = None) -> tuple[Agent, ParachuteContext]:
    config = load_config()
    context = build_context(config, architecture="centralized")
    model = model or build_model(config)

    faq_agent = build_faq_agent(model)
    weather_agent = build_weather_agent(model)
    scheduling_agent = build_scheduling_agent(model)

    supervisor = Agent(
        name="Central Supervisor",
        instructions=SUPERVISOR_INSTRUCTIONS,
        model=model,
        tool_use_behavior=booking_result_or_continue,
        tools=[
            faq_agent.as_tool(
                tool_name="faq_specialist",
                tool_description="Responde preguntas frecuentes sobre el evento de paracaidismo.",
            ),
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
    return supervisor, context


def main() -> int:
    configure_logging()
    try:
        supervisor, context = build_supervisor()
    except ConfigError as error:
        print(f"Error de configuracion: {error}", file=sys.stderr)
        return 2

    run_chat(supervisor, context, "centralizada")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
