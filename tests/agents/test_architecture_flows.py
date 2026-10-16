"""Real Agents SDK runs of the three architectures with a scripted, network-free model."""

from datetime import date

import pytest

from evals.fixtures.calendar import make_calendar_service
from evals.fixtures.weather import make_weather_service
from src.agents.centralized.evaluation import run_centralized_session_async
from src.agents.centralized.main import build_supervisor
from src.agents.common.grounding import DOMAIN_ABSTENTION
from src.agents.decentralized.main import build_entry_agent
from src.agents.hierarchical.main import build_root_manager
from tests.agents.scripted_model import ScriptedModel, sequence

TODAY = date(2026, 9, 17)
DAY = "2026-09-20"
REQUEST = f"Reserva el {DAY} para Ana Ejemplo, ana@example.invalid, somos 2 personas."
CONFIRM = f"Acepto tándem experimentado para {DAY}."

SUPERVISOR = "Eres el supervisor central"
ROOT = "Eres el Root Manager"
KNOWLEDGE = "Eres el Knowledge Manager"
BOOKING = "Eres el Booking Manager"
FAQ = "Eres el especialista en preguntas frecuentes"
WEATHER = "Eres el especialista en clima"
SCHEDULING = "Eres el especialista en calendarizacion"


@pytest.fixture(autouse=True)
def llm_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")


def _say(text):
    return ("message", text)


def _echo_first_output(prefix=""):
    return lambda _user, outputs: ("message", prefix + outputs[0])


WEATHER_SCRIPT = sequence(("tool", "check_jump_day", {"date_str": DAY}), _echo_first_output())
SCHEDULING_SCRIPT = sequence(
    ("tool", "check_appointment_availability", {"date_str": DAY}),
    ("tool", "create_appointment", {"date_str": DAY}),
    _say("Listo."),
)
FAQ_SCRIPT = sequence(lambda user, _o: ("tool", "search_faq", {"query": user}))


def _decentralized_scripts(booking_says=None):
    handoff = {"reason": "reserva"}
    return {
        FAQ: lambda user, outputs: (
            ("tool", "transfer_to_weather_agent", handoff) if "eserv" in user or "cepto" in user
            else ("tool", "search_faq", {"query": user}) if not outputs
            else ("message", outputs[0])
        ),
        WEATHER: sequence(
            ("tool", "check_jump_day", {"date_str": DAY}),
            ("tool", "transfer_to_scheduling_agent", handoff),
        ),
        SCHEDULING: SCHEDULING_SCRIPT,
    }


def _builders(scripts_by_arch):
    return {
        "centralized": lambda: build_supervisor(ScriptedModel(scripts_by_arch["centralized"])),
        "hierarchical": lambda: build_root_manager(ScriptedModel(scripts_by_arch["hierarchical"])),
        "decentralized": lambda: build_entry_agent(ScriptedModel(scripts_by_arch["decentralized"])),
    }


async def _run(build, turns, weather="ideal", calendar="empty"):
    return await run_centralized_session_async(
        turns, build=build, weather_service=make_weather_service(weather),
        calendar_service=make_calendar_service(calendar), fixed_today=TODAY,
    )


def _tools(result):
    return [event["tool"] for event in result.tool_calls]


FAQ_FLOW = {
    "centralized": {
        SUPERVISOR: sequence(lambda u, o: ("tool", "faq_specialist", {"input": u}), _echo_first_output()),
        FAQ: FAQ_SCRIPT,
    },
    "hierarchical": {
        ROOT: sequence(lambda u, o: ("tool", "knowledge_manager", {"input": u}), _echo_first_output()),
        KNOWLEDGE: sequence(lambda u, o: ("tool", "faq_specialist", {"input": u}), _echo_first_output()),
        FAQ: FAQ_SCRIPT,
    },
    "decentralized": _decentralized_scripts(),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("architecture", ["centralized", "hierarchical", "decentralized"])
async def test_faq_flow(architecture):
    result = await _run(_builders(FAQ_FLOW)[architecture], ["¿Cuál es el límite de peso?"])
    assert "100 kg" in result.answer
    assert _tools(result) == ["search_faq"]


BOOKING_FLOW = {
    "centralized": {
        SUPERVISOR: lambda user, outputs: (
            ("tool", "scheduling_specialist", {"input": f"Crea la cita del {DAY}"}) if "cepto" in user
            else sequence(
                ("tool", "weather_specialist", {"input": f"Evalua {DAY}"}),
                ("tool", "scheduling_specialist", {"input": f"Crea la cita del {DAY}"}),
                _echo_first_output(),
            )(user, outputs)
        ),
        WEATHER: WEATHER_SCRIPT,
        SCHEDULING: SCHEDULING_SCRIPT,
    },
    "hierarchical": {
        ROOT: sequence(lambda u, o: ("tool", "booking_manager", {"input": u}), _echo_first_output()),
        BOOKING: lambda user, outputs: (
            ("tool", "scheduling_specialist", {"input": f"Crea la cita del {DAY}"}) if "cepto" in user
            else sequence(
                ("tool", "weather_specialist", {"input": f"Evalua {DAY}"}),
                ("tool", "scheduling_specialist", {"input": f"Crea la cita del {DAY}"}),
                _echo_first_output(),
            )(user, outputs)
        ),
        WEATHER: WEATHER_SCRIPT,
        SCHEDULING: SCHEDULING_SCRIPT,
    },
    "decentralized": _decentralized_scripts(),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("architecture", ["centralized", "hierarchical", "decentralized"])
async def test_ideal_booking_flow(architecture):
    result = await _run(_builders(BOOKING_FLOW)[architecture], [REQUEST])
    assert result.answer.startswith(f"Cita confirmada (id=")
    assert DAY in result.answer and "participantes: 2" in result.answer
    assert _tools(result) == ["check_jump_day", "check_appointment_availability", "create_appointment"]


MARGINAL_FLOW = {
    "centralized": {
        SUPERVISOR: lambda user, outputs: (
            ("tool", "scheduling_specialist", {"input": f"Crea la cita del {DAY}"}) if "cepto" in user and not outputs
            else ("tool", "weather_specialist", {"input": f"Evalua {DAY}"}) if not outputs
            else ("message", "Es MARGINAL: confirma el tándem experimentado.")
        ),
        WEATHER: WEATHER_SCRIPT,
        SCHEDULING: SCHEDULING_SCRIPT,
    },
    "hierarchical": {
        ROOT: sequence(lambda u, o: ("tool", "booking_manager", {"input": u}), _echo_first_output()),
        BOOKING: lambda user, outputs: (
            ("tool", "scheduling_specialist", {"input": f"Crea la cita del {DAY}"}) if "cepto" in user and not outputs
            else ("tool", "weather_specialist", {"input": f"Evalua {DAY}"}) if not outputs
            else ("message", "Es MARGINAL: confirma el tándem experimentado.")
        ),
        WEATHER: WEATHER_SCRIPT,
        SCHEDULING: SCHEDULING_SCRIPT,
    },
    "decentralized": {
        FAQ: lambda user, outputs: ("tool", "transfer_to_weather_agent", {"reason": "reserva"}),
        WEATHER: lambda user, outputs: (
            ("tool", "transfer_to_scheduling_agent", {"reason": "confirmado"}) if "cepto" in user
            else ("tool", "check_jump_day", {"date_str": DAY}) if not outputs
            else ("message", "Es MARGINAL: confirma el tándem experimentado.")
        ),
        SCHEDULING: SCHEDULING_SCRIPT,
    },
}


@pytest.mark.asyncio
@pytest.mark.parametrize("architecture", ["centralized", "hierarchical", "decentralized"])
async def test_marginal_booking_in_two_turns(architecture):
    result = await _run(_builders(MARGINAL_FLOW)[architecture], [REQUEST, CONFIRM], weather="marginal_wind_upper")
    assert result.answer.startswith("Cita confirmada") and "tandem con instructor experimentado" in result.answer
    successes = [event["tool"] for event in result.tool_calls if event["status"] == "success"]
    assert successes[-3:] == ["check_jump_day", "check_appointment_availability", "create_appointment"]
    assert result.confirmed_tandem_date == DAY
    assert result.tool_calls[-1]["arguments"]["is_experienced_tandem"] is True


PROHIBITED_FLOW = {
    "centralized": {
        SUPERVISOR: sequence(("tool", "weather_specialist", {"input": f"Evalua {DAY}"}), _say("Tu cita quedó confirmada.")),
        WEATHER: WEATHER_SCRIPT,
    },
    "hierarchical": {
        ROOT: sequence(lambda u, o: ("tool", "booking_manager", {"input": u}), _say("Tu cita quedó confirmada.")),
        BOOKING: sequence(("tool", "weather_specialist", {"input": f"Evalua {DAY}"}), _echo_first_output()),
        WEATHER: WEATHER_SCRIPT,
    },
    "decentralized": {
        FAQ: sequence(("tool", "transfer_to_weather_agent", {"reason": "reserva"})),
        WEATHER: sequence(("tool", "check_jump_day", {"date_str": DAY}), _say("Tu cita quedó confirmada.")),
    },
}


@pytest.mark.asyncio
@pytest.mark.parametrize("architecture", ["centralized", "hierarchical", "decentralized"])
async def test_prohibited_weather_never_books_and_false_claims_are_corrected(architecture):
    result = await _run(_builders(PROHIBITED_FLOW)[architecture], [REQUEST], weather="prohibited_wind")
    assert "confirmada" not in result.answer
    assert "PROHIBITED" in result.answer
    assert "create_appointment" not in _tools(result)


OUT_OF_DOMAIN_FLOW = {
    "centralized": {SUPERVISOR: sequence(_say("Bobby Fischer ganó el mundial de ajedrez de 1972."))},
    "hierarchical": {ROOT: sequence(_say("Bobby Fischer ganó el mundial de ajedrez de 1972."))},
    "decentralized": {FAQ: sequence(_say("Bobby Fischer ganó el mundial de ajedrez de 1972."))},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("architecture", ["centralized", "hierarchical", "decentralized"])
async def test_out_of_domain_answer_is_replaced_by_the_domain_abstention(architecture):
    result = await _run(_builders(OUT_OF_DOMAIN_FLOW)[architecture], ["¿Quién ganó el mundial de ajedrez de 1972?"])
    assert result.answer == DOMAIN_ABSTENTION
    assert result.tool_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("architecture", ["centralized", "hierarchical", "decentralized"])
async def test_combined_booking_and_faq_keeps_both_answers(architecture):
    message = f"Reserva el {DAY} para Ana Ejemplo, ana@example.invalid, y dime qué ropa debo llevar."
    result = await _run(_builders(BOOKING_FLOW)[architecture], [message])
    assert result.answer.startswith("Cita confirmada (id=")
    assert "ropa cómoda y deportiva" in result.answer
    tools = _tools(result)
    assert tools[:3] == ["check_jump_day", "check_appointment_availability", "create_appointment"]
    assert "search_faq" in tools


@pytest.mark.asyncio
async def test_capacity_exhausted_is_reported_without_booking():
    result = await _run(_builders(BOOKING_FLOW)["centralized"], [REQUEST], calendar="full_2026_09_20")
    assert "create_appointment" not in [
        event["tool"] for event in result.tool_calls if event["result"].get("created") is True
    ]
    assert "Cita confirmada" not in result.answer
