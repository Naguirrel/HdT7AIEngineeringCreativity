"""Promptfoo Python provider. Output is only the final answer; trace stays in metadata."""

from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.exceptions import AgentsException
import openai
from pydantic import ValidationError

from src.agents.centralized.evaluation import run_centralized_session_async
from src.config import ConfigError
from evals.fixtures.calendar import make_calendar_service
from evals.fixtures.weather import FixtureError, make_weather_service

DEFAULT_FIXED_TODAY = "2026-09-17"


class ScenarioError(ValueError):
    """The Promptfoo test case itself is malformed (not a model or provider failure)."""


def _parse_scenario(prompt, variables: dict) -> tuple[list[str], date, dict[str, str]]:
    turns = variables.get("turns", prompt)
    if isinstance(turns, str):
        turns = [turns]
    if not isinstance(turns, list) or not turns or any(not isinstance(t, str) or not t.strip() for t in turns):
        raise ScenarioError("turns debe ser una cadena o una lista de mensajes no vacios.")
    try:
        fixed_today = date.fromisoformat(str(variables.get("fixed_today", DEFAULT_FIXED_TODAY)))
    except ValueError as error:
        raise ScenarioError("fixed_today debe tener formato YYYY-MM-DD.") from error
    expected_identity = {
        field: variables[key]
        for key, field in (("expect_customer_name", "customer_name"), ("expect_contact", "contact"))
        if key in variables
    }
    return turns, fixed_today, expected_identity


async def call_api(prompt, options, context):
    """Return a Promptfoo ProviderResponse for one isolated scenario.

    Errors are classified so a provider/quota problem is never confused with a wrong
    agent answer, and no message from the model provider is echoed (it may hold details).
    """
    variables = context.get("vars", {})
    try:
        turns, fixed_today, expected_identity = _parse_scenario(prompt, variables)
        weather_fixture = variables.get("weather_fixture", "ideal")
        calendar_fixture = variables.get("calendar_fixture", "empty")
        weather_service = make_weather_service(weather_fixture)
        calendar_service = make_calendar_service(calendar_fixture)
    except ScenarioError as error:
        return {"error": f"Escenario invalido: {error}"}
    except FixtureError as error:
        return {"error": f"Fixture invalido: {error}"}

    try:
        result = await run_centralized_session_async(
            turns, fixed_today=fixed_today, weather_service=weather_service,
            calendar_service=calendar_service, expected_identity=expected_identity,
        )
    except ConfigError as error:
        return {"error": f"Configuracion: {error}"}
    except (openai.RateLimitError, openai.APIError) as error:
        return {"error": f"Proveedor LLM: {type(error).__name__}"}
    except (json.JSONDecodeError, ValidationError) as error:
        return {"error": f"Respuesta invalida del modelo: {type(error).__name__}"}
    except AgentsException as error:
        return {"error": f"Agente: {type(error).__name__}"}
    except Exception as error:
        return {"error": f"Fallo durante la ejecucion: {type(error).__name__}"}
    return {
        "output": result.answer,
        "metadata": {
            "scenario": variables.get("scenario", "unknown"),
            "tool_calls": result.tool_calls,
            "retrieved_context": result.retrieved_context,
            "latency_ms": result.latency_ms,
            "weather_fixture": weather_fixture,
            "calendar_fixture": calendar_fixture,
            "weather_requests": result.weather_requests,
            "real_open_meteo_contacted": False,
            "confirmed_tandem_date": result.confirmed_tandem_date,
            "identity_checks": result.identity_checks,
        },
        "latencyMs": result.latency_ms,
    }
