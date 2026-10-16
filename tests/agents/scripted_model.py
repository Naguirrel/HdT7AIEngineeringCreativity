"""A deterministic, network-free Model for running real Agents SDK flows in tests.

Each agent is identified by a unique fragment of its system instructions. Its script is a
function (last_user_text, own_tool_outputs) -> ("tool", name, arguments) | ("message", text)
that decides the next step, exactly like an LLM would, but reproducibly.
"""

import itertools
import json
from collections.abc import Callable

from agents import Model, ModelResponse, Usage
from openai.types.responses import (
    ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText,
)

Step = tuple
Script = Callable[[str, list[str]], Step]


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


class ScriptedModel(Model):
    def __init__(self, scripts: dict[str, Script]):
        self.scripts = scripts
        self.calls: list[tuple[str, Step]] = []
        self._ids = itertools.count(1)

    def _script_for(self, instructions: str | None) -> tuple[str, Script]:
        for marker, script in self.scripts.items():
            if instructions and marker in instructions:
                return marker, script
        raise AssertionError(f"No script for agent: {(instructions or '')[:60]!r}")

    async def get_response(self, system_instructions, input, model_settings, tools, output_schema,
                           handoffs, tracing, *, previous_response_id=None, conversation_id=None,
                           prompt=None, **kwargs):
        marker, script = self._script_for(system_instructions)
        items = [{"role": "user", "content": input}] if isinstance(input, str) else list(input)
        last_user = max((index for index, item in enumerate(items) if item.get("role") == "user"), default=0)
        own_names = {tool.name for tool in tools} | {handoff.tool_name for handoff in handoffs}
        own_calls = {
            item.get("call_id") for item in items[last_user:]
            if item.get("type") == "function_call" and item.get("name") in own_names
        }
        outputs = [
            str(item.get("output")) for item in items[last_user:]
            if item.get("type") == "function_call_output" and item.get("call_id") in own_calls
        ]
        step = script(_text(items[last_user].get("content")), outputs)
        self.calls.append((marker, step))
        number = next(self._ids)
        if step[0] == "tool":
            output = [ResponseFunctionToolCall(
                id=f"fc_{number}", call_id=f"call_{number}", name=step[1],
                arguments=json.dumps(step[2]), type="function_call",
            )]
        else:
            output = [ResponseOutputMessage(
                id=f"msg_{number}", role="assistant", status="completed", type="message",
                content=[ResponseOutputText(text=step[1], type="output_text", annotations=[])],
            )]
        return ModelResponse(output=output, usage=Usage(), response_id=None)

    def stream_response(self, *args, **kwargs):
        raise NotImplementedError("Streaming is not used by these tests.")


def sequence(*steps: Step) -> Script:
    """Script that returns step N after N of its own tool outputs (then the last step)."""
    def script(_user: str, outputs: list[str]) -> Step:
        step = steps[min(len(outputs), len(steps) - 1)]
        return step(_user, outputs) if callable(step) else step
    return script
