"""Loop de conversacion compartido por las tres arquitecturas (async, via Runner.run)."""

import asyncio

from agents import Agent, Runner

from src.agents.common.context import ParachuteContext
from src.agents.common.booking_completion import finish_turn
from src.observability import log_event, user_facing_error


async def run_chat_async(starting_agent: Agent, context: ParachuteContext, architecture_name: str) -> None:
    print(f"Parachute S.A. -- arquitectura {architecture_name}")
    print("Escribe 'Bye' o presiona Ctrl-C para salir.\n")

    current_agent = starting_agent
    history: list[dict] = []

    while True:
        try:
            question = input("Tu: ")
        except (KeyboardInterrupt, EOFError):
            print("\n¡Hasta luego!")
            return

        clean_question = question.strip()
        if clean_question.casefold() == "bye":
            print("¡Hasta luego!")
            return
        if not clean_question:
            continue

        context.observe_user_message(clean_question)
        history.append({"role": "user", "content": clean_question})
        log_event(architecture=architecture_name, agent=current_agent.name)
        try:
            result = await Runner.run(current_agent, history, context=context)
        except Exception as error:
            print(user_facing_error(error, architecture=architecture_name, stage="runner"))
            continue

        if result.last_agent.name != current_agent.name:
            log_event(
                architecture=architecture_name,
                handoff=f"{current_agent.name}->{result.last_agent.name}",
            )

        print(f"[{result.last_agent.name}]: {finish_turn(context, result.final_output)}\n")
        history = result.to_input_list()
        current_agent = result.last_agent


def run_chat(starting_agent: Agent, context: ParachuteContext, architecture_name: str) -> None:
    asyncio.run(run_chat_async(starting_agent, context, architecture_name))
