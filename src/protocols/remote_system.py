"""Run the existing central supervisor with exclusively remote business tools."""

import json
from copy import deepcopy

from agents import Agent, FunctionTool, ModelSettings, Runner, ToolsToFinalOutputResult
from agents.mcp import MCPServerStreamableHttp

from src.agents.centralized.main import SUPERVISOR_INSTRUCTIONS
from src.agents.common.booking_completion import SCHEDULING_TOOL_NAMES
from src.agents.common.specialist_agents import (
    build_faq_agent, build_scheduling_agent, build_weather_agent,
)


class RemoteTools:
    def __init__(self, server, session_id):
        self.server, self.session_id = server, session_id

    async def call(self, name, **arguments):
        result = await self.server.call_tool(name, {"session_id": self.session_id, **arguments})
        if getattr(result, "is_error", getattr(result, "isError", False)):
            raise RuntimeError("Fallo una herramienta del servidor MCP.")
        return "\n".join(part.text for part in result.content if getattr(part, "type", None) == "text")

    def proxy(self, tool):
        # Preserve the existing, strict LLM schema. The session is injected by
        # trusted application code, never supplied or changed by the LLM.
        async def invoke(_wrapper, arguments):
            return await self.call(tool.name, **json.loads(arguments))
        return FunctionTool(name=tool.name, description=tool.description,
                            params_json_schema=deepcopy(tool.params_json_schema), on_invoke_tool=invoke)

    async def completion(self, _wrapper, _results):
        if not any(result.tool.name in SCHEDULING_TOOL_NAMES for result in _results):
            return ToolsToFinalOutputResult(is_final_output=False, final_output=None)
        text = await self.call("complete_booking")
        return ToolsToFinalOutputResult(is_final_output=bool(text), final_output=text or None)


def build_remote_supervisor(model, remote):
    faq = build_faq_agent(model)
    weather = build_weather_agent(model)
    scheduling = build_scheduling_agent(model)
    for specialist in (faq, weather, scheduling):
        specialist.tools = [remote.proxy(tool) for tool in specialist.tools]
        specialist.model_settings = ModelSettings(parallel_tool_calls=False)
    scheduling.tool_use_behavior = remote.completion
    return Agent(
        name="Parachute Supervisor (MCP)", instructions=SUPERVISOR_INSTRUCTIONS,
        model=model, model_settings=ModelSettings(parallel_tool_calls=False),
        tool_use_behavior=remote.completion,
        tools=[
            faq.as_tool(tool_name="faq_specialist", tool_description="Consulta las FAQ oficiales."),
            weather.as_tool(tool_name="weather_specialist", tool_description="Evalua clima y seguridad."),
            scheduling.as_tool(tool_name="scheduling_specialist", tool_description="Comprueba cupo y crea citas."),
        ],
    )


class Conversation:
    def __init__(self):
        self.session_id = None
        self.history = []

    async def turn(self, text, *, mcp_url, model):
        # Enter and exit the MCP context in this same task (AnyIO cancellation
        # scopes must not be opened in one request and closed in another).
        async with MCPServerStreamableHttp(
            name="Parachute MCP", params={"url": mcp_url, "timeout": 30},
            client_session_timeout_seconds=60,
        ) as server:
            if self.session_id is None:
                result = await server.call_tool("open_conversation", {})
                if getattr(result, "is_error", getattr(result, "isError", False)):
                    raise RuntimeError("No se pudo abrir una sesion MCP.")
                self.session_id = next(part.text for part in result.content if part.type == "text")
            remote = RemoteTools(server, self.session_id)
            await remote.call("begin_turn", message=text)
            supervisor = build_remote_supervisor(model, remote)
            inputs = self.history + [{"role": "user", "content": text}]
            result = await Runner.run(supervisor, inputs, max_turns=30)
            answer = await remote.call("finalize_turn", model_output=str(result.final_output))
            # Keep only the corrected response in history, never an ungrounded
            # model claim that could contradict authoritative calendar state.
            self.history = (self.history + [
                {"role": "user", "content": text}, {"role": "assistant", "content": answer},
            ])[-40:]
            return answer
