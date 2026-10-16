"""Deterministic grounding of exact entities (AUD-010)."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from src.agents.centralized.evaluation import run_centralized_session_async
from src.agents.common.booking_completion import finish_turn
from src.agents.common.grounding import DOMAIN_ABSTENTION, ground_answer, ungrounded_entities
from src.tools.faq_tools import answer_from_faq
from src.tools.weather_tools import evaluate_jump_day
from tests.agents.conftest import FIXED_TODAY, make_snapshot


def _faq_turn(build_context, question, query=None):
    context = build_context({})
    context.observe_user_message(question)
    answer_from_faq(context, query or question)
    return context


@pytest.mark.parametrize(("question", "answer"), [
    ("¿Cuál es el teléfono?", "El teléfono de contacto es **+502 2300‑0000** (también WhatsApp)."),
    ("¿Cuál es el correo?", "Escribe a info@parachutesa.gt o visita www.parachutesa.gt."),
    ("¿Dónde es el evento?",
     "Será el **29 de septiembre de 2026** en la Pista de Aterrizaje de Puerto San José, Escuintla, a las 07:00 AM."),
    ("¿Cuál es el límite de peso?", "El límite es de 100 kg (220 lbs)."),
    ("Tengo 17 años, ¿qué necesito?", "Con 17 años debes ir acompañado por tus padres o tutores legales."),
])
def test_grounded_entities_are_kept(build_context, question, answer):
    context = _faq_turn(build_context, question)
    assert ground_answer(context, answer) == answer


@pytest.mark.parametrize(("question", "answer", "bad"), [
    ("¿Cuál es el teléfono?", "El teléfono de Parachute S.A. es +1 (555) 123-4567.", "+1 (555) 123-4567"),
    ("¿Dónde es el evento?", "El evento será el 17 de agosto de 2026.", "17/8/2026"),
    ("¿Dónde es el evento?", "Será en la Base Aérea de Santa Lucía.", "Base Aérea de Santa Lucía"),
    ("¿Dónde es el evento?", "Empieza a las 08:30 AM.", "08:30"),
    ("¿Cuál es el límite de peso?", "El límite es de 1100 kg.", "1100"),
    ("¿Cuál es el correo?", "Escribe a ventas@parachute.com.", "ventas@parachute.com"),
    ("¿Cuánto cuesta el salto tándem básico?", "El salto tándem básico cuesta Q450.", "q450"),
])
def test_invented_entities_are_replaced_by_the_retrieved_faq_text(build_context, question, answer, bad):
    context = _faq_turn(build_context, question)
    violations = ungrounded_entities(answer, "\n".join(e["answer"] for e in context.turn_faq_entries))
    assert any(bad.lower() in item.lower() for item in violations)
    grounded = ground_answer(context, answer)
    assert bad.lower() not in grounded.lower()
    if context.turn_faq_entries:
        assert grounded.startswith("Segun las FAQ oficiales de Parachute S.A.:")
        assert context.turn_faq_entries[0]["answer"] in grounded
    else:
        assert "No encontre ese dato" in grounded


def test_answer_without_entities_is_unchanged(build_context):
    context = _faq_turn(build_context, "¿Puedo llevar mi GoPro?")
    answer = "No, por seguridad no se permite llevar cámaras durante el salto."
    assert ground_answer(context, answer) == answer


@pytest.mark.parametrize("answer", [
    "Llama al +502 5555-1234 para más información.",
    "Bobby Fischer ganó el campeonato mundial.",
    "El evento es el 30 de octubre de 2026.",
])
def test_empty_context_turns_cannot_present_exact_entities(build_context, answer):
    context = build_context({})
    context.observe_user_message("Hola, una pregunta")
    assert ground_answer(context, answer) == DOMAIN_ABSTENTION


@pytest.mark.parametrize("answer", ["¡Hola! ¿En qué puedo ayudarte hoy?", "¡Hasta luego! Gracias por escribir."])
def test_greetings_without_entities_pass(build_context, answer):
    context = build_context({})
    context.observe_user_message("Hola")
    assert ground_answer(context, answer) == answer


def test_weather_numbers_from_the_tool_are_grounded_and_invented_ones_removed(build_context):
    day = FIXED_TODAY + timedelta(days=3)
    context = build_context({day: make_snapshot(day, wind_speed_10m_kmh=28.1)})
    context.observe_user_message(f"¿Puedo saltar el {day.isoformat()}?")
    evaluate_jump_day(context, day.isoformat())
    answer = (
        "El 20 de septiembre de 2026 está PROHIBIDO: viento de 28.1 km/h supera el límite de 28 km/h. "
        "Llama al +502 9999-8888 para reprogramar."
    )
    grounded = ground_answer(context, answer)
    assert "28.1 km/h" in grounded and "9999" not in grounded


@pytest.mark.asyncio
async def test_runner_applies_grounding_in_evaluation(build_context):
    context = build_context({})
    agent = SimpleNamespace(name="Central Supervisor")

    async def fake_run(agent, history, *, context):
        answer_from_faq(context, "teléfono de contacto")
        return SimpleNamespace(final_output="Llama al +1 (555) 123-4567.", last_agent=agent, to_input_list=lambda: history)

    result = await run_centralized_session_async(
        ["¿Cuál es el teléfono?"], build=lambda: (agent, context), run=fake_run,
    )
    assert "555" not in result.answer and "+502 2300-0000" in result.answer


def test_finish_turn_grounds_before_checking_booking_claims(build_context):
    context = build_context({})
    context.observe_user_message("¿Dónde es el evento?")
    assert finish_turn(context, "Bobby Fischer te espera en la pista.") == DOMAIN_ABSTENTION
