"""Programmatic runner for evaluating the real centralized supervisor."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from time import perf_counter

from agents import Runner, set_tracing_disabled
from openai import AsyncOpenAI

from src.agents.centralized.main import build_supervisor
from src.agents.common.booking_completion import finish_turn
from src.tools.calendar_tools import contact_identity

# Business traces stay local; the SDK must never export prompts, tool arguments or
# personal data to a remote tracing backend, even if OPENAI_API_KEY is set.
set_tracing_disabled(True)

_PSEUDONYM_FIELDS = {"customer_name_hmac": "customer_name", "contact_hmac": "contact"}


@dataclass(frozen=True)
class EvaluationResult:
    answer: str
    tool_calls: list[dict]
    retrieved_context: list[dict[str, str]]
    latency_ms: int
    weather_requests: list[str] | None = None
    confirmed_tandem_date: str | None = None
    identity_checks: dict[str, bool] = field(default_factory=dict)


def _exportable_trace(trace: list[dict]) -> list[dict]:
    """Drop session pseudonyms: they are useless outside the session and need not leave it."""
    exported = []
    for event in trace:
        arguments = {
            key: value for key, value in event["arguments"].items()
            if not key.endswith("_hmac") and not key.endswith("_sha256")
        }
        exported.append({**event, "arguments": arguments})
    return exported


def _identity_checks(context, trace: list[dict], expected: Mapping[str, str]) -> dict[str, bool]:
    """Compare expected test identities with the last create_appointment, inside the session."""
    bookings = [event for event in trace if event["tool"] == "create_appointment"]
    if not expected or not bookings:
        return {}
    arguments = bookings[-1]["arguments"]
    checks = {}
    for key, field_name in _PSEUDONYM_FIELDS.items():
        if field_name in expected:
            value = expected[field_name]
            value = contact_identity(value) if field_name == "contact" else value
            checks[field_name] = arguments.get(key) is not None and arguments.get(key) == context.pseudonymize(value)
    return checks


async def run_centralized_session_async(
    turns: Sequence[str],
    *,
    build: Callable = build_supervisor,
    run: Callable = Runner.run,
    weather_service=None,
    calendar_service=None,
    fixed_today: date | None = None,
    expected_identity: Mapping[str, str] | None = None,
) -> EvaluationResult:
    """Create fresh agent, services, context, history and calendar for each case."""
    if not turns or any(not isinstance(turn, str) or not turn.strip() for turn in turns):
        raise ValueError("La evaluacion requiere uno o mas mensajes no vacios.")
    set_tracing_disabled(True)
    started = perf_counter()
    supervisor, context = build()
    # build_supervisor creates one AsyncOpenAI client for this session's shared model.
    # Close it before the event loop of this call ends (Promptfoo runs asyncio.run per call).
    client = getattr(getattr(supervisor, "model", None), "_client", None)
    try:
        if calendar_service is not None:
            context.services.calendar_service = calendar_service
        if weather_service is not None:
            context.services.weather_service = weather_service
        if fixed_today is not None:
            context.today = lambda: fixed_today

        history: list[dict] = []
        current_agent = supervisor
        answer = ""
        for turn in turns:
            context.observe_user_message(turn)
            history.append({"role": "user", "content": turn})
            result = await run(current_agent, history, context=context)
            answer = finish_turn(context, result.final_output)
            if not isinstance(answer, str) or not answer.strip():
                raise RuntimeError("El modelo devolvio una respuesta vacia.")
            history = result.to_input_list()
            current_agent = result.last_agent

        trace = context.get_tool_trace()
        return EvaluationResult(
            answer=answer,
            tool_calls=_exportable_trace(trace),
            retrieved_context=context.get_retrieved_context(),
            latency_ms=round((perf_counter() - started) * 1000),
            weather_requests=[value.isoformat() for value in weather_service.client.calls]
            if weather_service is not None else None,
            confirmed_tandem_date=context.confirmed_tandem_date.isoformat()
            if context.confirmed_tandem_date is not None else None,
            identity_checks=_identity_checks(context, trace, expected_identity or {}),
        )
    finally:
        if isinstance(client, AsyncOpenAI):
            await client.close()
