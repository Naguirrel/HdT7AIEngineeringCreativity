"""Smoke test manual (no pytest): corre una conversacion real contra Groq + Open-Meteo
para cada arquitectura y deja evidencia en docs/smoke-test-output.txt.

No forma parte de la suite automatizada porque depende de red y de un LLM real
(no deterministico). Usa la misma ruta que la CLI y la evaluacion: reloj de
Guatemala, observe_user_message y finish_turn (finalizacion determinista, guarda de
veracidad y grounding), y cierra el cliente del modelo de cada arquitectura.
"""

import asyncio
import sys
from datetime import date, timedelta

from agents import Runner
from openai import AsyncOpenAI

from src.agents.centralized.main import build_supervisor
from src.agents.common.booking_completion import finish_turn
from src.agents.decentralized.main import build_entry_agent
from src.agents.hierarchical.main import build_root_manager
from src.domain.clock import current_guatemala_date
from src.observability import configure_logging, user_facing_error


def build_script(today: date) -> list[str]:
    valid_date = (today + timedelta(days=3)).isoformat()
    out_of_range_date = (today + timedelta(days=200)).isoformat()
    return [
        "¿Cuál es la edad mínima para poder saltar?",
        f"Quiero saltar el {valid_date}. Resérvame a nombre de Ana Lopez, contacto ana@example.com.",
        f"¿Puedo reservar para el {out_of_range_date}?",
    ]


async def run_architecture(name: str, starting_agent, context, script: list[str], run=Runner.run) -> list[str]:
    lines = [f"=== {name} ==="]
    current_agent = starting_agent
    history: list[dict] = []
    for turn in script:
        context.observe_user_message(turn)
        history.append({"role": "user", "content": turn})
        lines.append(f"Usuario: {turn}")
        try:
            result = await run(current_agent, history, context=context)
        except Exception as error:
            lines.append(f"[ERROR] {user_facing_error(error, architecture=name, stage='smoke')}")
            continue
        lines.append(f"[{result.last_agent.name}]: {finish_turn(context, result.final_output)}")
        history = result.to_input_list()
        current_agent = result.last_agent
    lines.append("")
    return lines


async def close_model_client(agent) -> None:
    client = getattr(getattr(agent, "model", None), "_client", None)
    if isinstance(client, AsyncOpenAI):
        await client.close()


async def main() -> None:
    configure_logging()
    script = build_script(current_guatemala_date())

    all_lines: list[str] = []
    for name, build in (
        ("centralized", build_supervisor),
        ("hierarchical", build_root_manager),
        ("decentralized", build_entry_agent),
    ):
        agent, context = build()
        try:
            all_lines.extend(await run_architecture(name, agent, context, script))
        finally:
            await close_model_client(agent)

    output = "\n".join(all_lines)
    print(output)
    output_path = sys.argv[1] if len(sys.argv) > 1 else "docs/smoke-test-output.txt"
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(output)


if __name__ == "__main__":
    asyncio.run(main())
