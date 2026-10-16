"""Terminal A2A client: no model, domain tools or LLM credentials in this process."""

import argparse
import asyncio
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, TextPart


def text_parts(parts):
    return "\n".join(part.root.text for part in parts if isinstance(part.root, TextPart))


class TerminalSession:
    def __init__(self, client):
        self.client = client
        self.context_id = None

    async def ask(self, text):
        message = Message(role="user", message_id=str(uuid4()), context_id=self.context_id,
                          parts=[Part(root=TextPart(text=text))])
        answers = []
        async for event in self.client.send_message(message):
            if isinstance(event, Message):
                self.context_id = event.context_id or self.context_id
                answers.append(text_parts(event.parts))
            else:
                task, _update = event
                self.context_id = task.context_id or self.context_id
                if task.artifacts:
                    answers.extend(text_parts(artifact.parts) for artifact in task.artifacts)
                elif task.status.message:
                    answers.append(text_parts(task.status.message.parts))
        return "\n".join(answer for answer in answers if answer)


async def run(url):
    async with httpx.AsyncClient(timeout=180) as http:
        card = await A2ACardResolver(httpx_client=http, base_url=url).get_agent_card()
        client = ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create(card)
        session = TerminalSession(client)
        print(f"Conectado por A2A: {card.name}")
        print("Skills: " + ", ".join(skill.name for skill in card.skills))
        print("Escribe Bye o presiona Ctrl-C para salir.\n")
        try:
            while True:
                try:
                    question = input("Tu: ").strip()
                except EOFError:
                    break
                if question.casefold() == "bye":
                    break
                if not question:
                    continue
                try:
                    print("Parachute: " + await session.ask(question) + "\n")
                except Exception as error:
                    print(f"Error de comunicacion A2A ({type(error).__name__}). Revisa ambos servidores.")
        finally:
            await client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.url))
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print(f"No se pudo conectar por A2A ({type(error).__name__}). Inicia el servidor A2A.")
        return 1
    print("¡Hasta luego!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
