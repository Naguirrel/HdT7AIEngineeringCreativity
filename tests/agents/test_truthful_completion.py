"""Truthful booking answers and deterministic completion (AUD-001, AUD-002)."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from agents import RunContextWrapper

from src.agents.centralized.evaluation import run_centralized_session_async
from src.agents.common.booking_completion import booking_result_or_continue, finish_turn
from src.agents.common.truthfulness import is_booking_claim
from src.tools.calendar_tools import book_appointment, evaluate_availability
from src.tools.weather_tools import evaluate_jump_day
from tests.agents.conftest import FIXED_TODAY, make_snapshot

DAY = FIXED_TODAY + timedelta(days=3)
ISO = DAY.isoformat()
REQUEST = f"Reserva el {ISO} para Ana Ejemplo, ana@example.invalid, somos 2 personas."


def _tools(context):
    return [event["tool"] for event in context.get_tool_trace()]


@pytest.mark.parametrize("text", [
    f"¡Listo! Tu cita para {ISO} quedó confirmada.",
    "Con esta información, la cita está confirmada para el 20 de septiembre.",
    "He reservado tu salto para el sábado.",
    "**Tu reserva ha quedado registrada** con éxito.",
])
def test_hallucinated_confirmation_without_record_is_replaced_by_real_state(build_context, text):
    context = build_context({DAY: make_snapshot(DAY)})
    context.observe_user_message(REQUEST)
    evaluate_jump_day(context, ISO)
    context.booking_request.contact = None  # completion impossible: data is missing
    answer = finish_turn(context, text)
    assert "Aun no se ha creado ninguna cita" in answer
    assert "contacto" in answer
    assert not any(is_booking_claim(part) for part in answer.split("."))
    assert context.appointment_record is None


@pytest.mark.parametrize("text", [
    "No se puede crear la cita: el clima lo prohíbe.",
    "La cita aún no fue creada; falta tu contacto.",
    "Si confirmas el tándem, la cita quedará reservada.",
    "¿Deseas que la cita quede confirmada para esa fecha?",
])
def test_negated_or_conditional_statements_are_not_claims(build_context, text):
    context = build_context({})
    assert finish_turn(context, text) == text


def test_real_creation_answer_is_derived_from_the_record(build_context):
    context = build_context({DAY: make_snapshot(DAY)})
    context.observe_user_message(REQUEST)
    evaluate_jump_day(context, ISO)
    evaluate_availability(context, ISO)
    book_appointment(context, ISO)
    answer = finish_turn(context, "No.")
    record = context.appointment_record
    assert answer.startswith(f"Cita confirmada (id={record.id}) para {ISO}")
    assert "participantes: 2" in answer
    assert "Ana Ejemplo" not in answer and "ana@example.invalid" not in answer


def test_specialist_without_forwarded_data_uses_session_data(build_context):
    context = build_context({DAY: make_snapshot(DAY)})
    context.observe_user_message(REQUEST)
    evaluate_jump_day(context, ISO)
    evaluate_availability(context, ISO)
    result = book_appointment(context, ISO)  # the supervisor forwarded no name/contact
    assert result.startswith("Cita confirmada")
    created = context.get_tool_trace()[-1]
    assert created["arguments"]["customer_name_provided"] and created["arguments"]["contact_provided"]
    assert created["arguments"]["party_size"] == 2


def test_scheduling_stop_after_availability_is_completed_deterministically(build_context):
    context = build_context({DAY: make_snapshot(DAY)})
    context.observe_user_message(REQUEST)
    evaluate_jump_day(context, ISO)
    evaluate_availability(context, ISO)  # the model stops here
    wrapper = RunContextWrapper(context=context)
    availability = SimpleNamespace(tool=SimpleNamespace(name="check_appointment_availability"), output="Hay cupo")
    result = booking_result_or_continue(wrapper, [availability])
    assert result.is_final_output and result.final_output.startswith("Cita confirmada")
    assert _tools(context) == ["check_jump_day", "check_appointment_availability", "create_appointment"]


def test_question_without_booking_intent_is_not_booked_automatically(build_context):
    context = build_context({DAY: make_snapshot(DAY)})
    context.observe_user_message(f"¿Se puede reservar el {ISO} para Ana Ejemplo, ana@example.invalid?")
    evaluate_jump_day(context, ISO)
    assert finish_turn(context, "Sí, el día es IDEAL.") == "Sí, el día es IDEAL."
    assert context.appointment_record is None


def _marginal_context(build_context, **overrides):
    return build_context({DAY: make_snapshot(DAY, wind_speed_10m_kmh=25.0, **overrides)})


def test_marginal_booking_in_two_turns_creates_the_appointment(build_context):
    context = _marginal_context(build_context)
    context.observe_user_message(REQUEST)
    evaluate_jump_day(context, ISO)
    first = finish_turn(context, "Es MARGINAL. ¿Aceptas tándem experimentado?")
    assert "Cita confirmada" not in first

    context.observe_user_message(f"Acepto tándem experimentado para {ISO}. Confirma la cita.")
    answer = finish_turn(context, "Para crear la cita necesito tu nombre y contacto.")
    assert answer.startswith("Cita confirmada") and "tandem con instructor experimentado" in answer
    assert _tools(context) == ["check_jump_day", "check_appointment_availability", "create_appointment"]
    assert context.get_tool_trace()[-1]["arguments"]["is_experienced_tandem"] is True


def test_same_day_marginal_recheck_keeps_confirmation_and_completes(build_context):
    context = _marginal_context(build_context)
    context.observe_user_message(REQUEST)
    evaluate_jump_day(context, ISO)
    context.observe_user_message(f"Acepto tándem experimentado para {ISO}.")
    evaluate_jump_day(context, ISO)  # the supervisor re-checks the same day
    assert context.confirmed_tandem_date == DAY
    assert finish_turn(context, "Listo.").startswith("Cita confirmada")


def test_date_change_revokes_confirmation(build_context):
    other = DAY + timedelta(days=1)
    context = build_context({
        DAY: make_snapshot(DAY, wind_speed_10m_kmh=25.0),
        other: make_snapshot(other, wind_speed_10m_kmh=25.0),
    })
    context.observe_user_message(REQUEST)
    evaluate_jump_day(context, ISO)
    context.observe_user_message("Acepto tándem experimentado.")
    evaluate_jump_day(context, other.isoformat())
    assert context.confirmed_tandem_date is None
    assert "Cita confirmada" not in finish_turn(context, "Listo.")


def test_decision_change_to_prohibited_revokes_confirmation(build_context):
    snapshots = {DAY: make_snapshot(DAY, wind_speed_10m_kmh=25.0)}
    context = build_context(snapshots)
    context.observe_user_message(REQUEST)
    evaluate_jump_day(context, ISO)
    context.observe_user_message("Acepto tándem experimentado.")
    snapshots[DAY] = make_snapshot(DAY, wind_speed_10m_kmh=30.0)
    evaluate_jump_day(context, ISO)
    assert context.confirmed_tandem_date is None
    answer = finish_turn(context, "Tu cita quedó confirmada.")
    assert "PROHIBITED" in answer and context.appointment_record is None


def test_local_day_change_revokes_confirmation(build_context):
    context = _marginal_context(build_context)
    context.observe_user_message(REQUEST)
    evaluate_jump_day(context, ISO)
    context.observe_user_message("Acepto tándem experimentado.")
    context.today = lambda: FIXED_TODAY + timedelta(days=1)
    evaluate_jump_day(context, ISO)
    assert context.confirmed_tandem_date is None


def test_user_rejection_revokes_confirmation_but_a_question_does_not(build_context):
    context = _marginal_context(build_context)
    evaluate_jump_day(context, ISO)
    context.observe_user_message("Acepto tándem experimentado.")
    context.observe_user_message("¿A qué hora debo llegar?")
    assert context.confirmed_tandem_date == DAY
    context.observe_user_message("No acepto el tándem, prefiero esperar.")
    assert context.confirmed_tandem_date is None


@pytest.mark.asyncio
async def test_runner_replaces_model_claim_without_success(build_context):
    context = build_context({DAY: make_snapshot(DAY)})
    agent = SimpleNamespace(name="Central Supervisor")

    async def fake_run(agent, history, *, context):
        evaluate_jump_day(context, ISO)
        return SimpleNamespace(
            final_output=f"Tu cita para {ISO} está confirmada.", last_agent=agent,
            to_input_list=lambda: history,
        )

    result = await run_centralized_session_async(
        [f"Reserva el {ISO} para Ana Ejemplo"], build=lambda: (agent, context), run=fake_run,
    )
    assert "Aun no se ha creado ninguna cita" in result.answer
    assert "contacto" in result.answer
    assert "create_appointment" not in [event["tool"] for event in result.tool_calls]


@pytest.mark.asyncio
async def test_runner_completes_marginal_booking_when_model_stalls(build_context):
    context = _marginal_context(build_context)
    agent = SimpleNamespace(name="Central Supervisor")
    replies = iter(["Es MARGINAL; confirma el tándem.", "Necesito tu nombre y contacto."])

    async def fake_run(agent, history, *, context):
        if len(history) == 1:
            evaluate_jump_day(context, ISO)
        return SimpleNamespace(final_output=next(replies), last_agent=agent, to_input_list=lambda: history)

    result = await run_centralized_session_async(
        [REQUEST, f"Acepto tándem experimentado para {ISO}. Confirma la cita."],
        build=lambda: (agent, context), run=fake_run,
    )
    assert result.answer.startswith("Cita confirmada")
    assert [event["tool"] for event in result.tool_calls] == [
        "check_jump_day", "check_appointment_availability", "create_appointment"
    ]
    assert result.confirmed_tandem_date == ISO


@pytest.mark.parametrize("text", ["No, la evaluación no es marginal.", "No.", "Lo siento, no se puede reservar ese día."])
def test_bookable_day_is_not_answered_with_a_refusal(build_context, text):
    # Regression from eval-Txz (appointment_last_valid): IDEAL + cupo, but the answer was "No, ...".
    context = build_context({DAY: make_snapshot(DAY)})
    context.observe_user_message(f"¿Se puede reservar el {ISO} para Ana Ejemplo, ana@example.invalid?")
    evaluate_jump_day(context, ISO)
    evaluate_availability(context, ISO)
    answer = finish_turn(context, text)
    assert answer.startswith(f"Si, el {ISO} se puede reservar: el clima evaluado es IDEAL.")
    assert "Hay cupo disponible." in answer
    assert context.appointment_record is None  # a question alone never books


def test_marginal_refusal_becomes_the_tandem_requirement(build_context):
    context = _marginal_context(build_context)
    context.observe_user_message(f"Reserva el {ISO} para Ana Ejemplo, ana@example.invalid.")
    evaluate_jump_day(context, ISO)
    answer = finish_turn(context, "No se puede reservar una cita individual para esa fecha.")
    assert "MARGINAL" in answer and "tandem con instructor experimentado" in answer
    assert f"Acepto tandem experimentado para {ISO}" in answer and "25.0 km/h" in answer


@pytest.mark.parametrize("weather", [{"precipitation_mm": 1.0}])
def test_refusals_stay_when_they_are_true(build_context, weather):
    context = build_context({DAY: make_snapshot(DAY, **weather)})
    context.observe_user_message(f"¿Se puede reservar el {ISO}?")
    evaluate_jump_day(context, ISO)
    answer = finish_turn(context, "No, el clima lo prohíbe.")
    assert answer.startswith("No, el clima lo prohíbe.") and "Precipitacion de 1.0 mm" in answer
    full = build_context({DAY: make_snapshot(DAY)})
    full.services.calendar_service.max_slots_per_day = 0
    full.observe_user_message(f"¿Se puede reservar el {ISO}?")
    evaluate_jump_day(full, ISO)
    evaluate_availability(full, ISO)
    assert finish_turn(full, "No, no hay cupo ese día.") == "No, no hay cupo ese día."


def test_marginal_answer_without_measured_value_gets_the_official_reason(build_context):
    # Regression from eval-oq5 (appointment_marginal_unconfirmed): MARGINAL explained without 20 km/h.
    context = build_context({DAY: make_snapshot(DAY, wind_speed_10m_kmh=20.0)})
    context.observe_user_message(REQUEST)
    evaluate_jump_day(context, ISO)
    text = "El clima es **MARGINAL**: solo tándem con instructor experimentado. Escribe 'Acepto tandem experimentado'."
    answer = finish_turn(context, text)
    assert answer.startswith(text)
    assert "20.0 km/h esta en rango marginal" in answer


def test_prohibited_answer_without_threshold_gets_the_official_reason(build_context):
    context = build_context({DAY: make_snapshot(DAY, wind_speed_10m_kmh=28.1)})
    context.observe_user_message(REQUEST)
    evaluate_jump_day(context, ISO)
    answer = finish_turn(context, "Lo siento, el viento excede el límite permitido; no se puede reservar.")
    assert "28.1 km/h supera el limite de 28 km/h" in answer


def test_reasons_are_not_repeated_when_already_stated(build_context):
    context = build_context({DAY: make_snapshot(DAY, wind_speed_10m_kmh=20.0)})
    context.observe_user_message(REQUEST)
    evaluate_jump_day(context, ISO)
    text = "Es MARGINAL por viento de 20 km/h; solo tándem con instructor experimentado."
    assert finish_turn(context, text) == text
