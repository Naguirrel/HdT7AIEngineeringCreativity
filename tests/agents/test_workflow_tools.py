"""Tests del flujo de negocio compartido detras de los tools de agentes.

Estas funciones (evaluate_jump_day, book_appointment, answer_from_faq) son las
que invocan las tres arquitecturas (centralizada, jerarquica, descentralizada),
por lo que probarlas aqui cubre el comportamiento comun a las tres.
"""

from datetime import timedelta

import pytest

from tests.agents.conftest import FIXED_TODAY, make_snapshot

from src.domain.weather_models import Decision
from src.integrations.open_meteo import OpenMeteoError
from src.services.weather_service import WeatherService
from src.tools.calendar_tools import book_appointment, evaluate_availability
from src.tools.faq_tools import answer_from_faq
from src.tools.weather_tools import evaluate_jump_day

TOMORROW = FIXED_TODAY + timedelta(days=1)


def test_answer_from_faq_returns_relevant_content(build_context):
    context = build_context({})
    answer = answer_from_faq(context, "edad minima")
    assert "P:" in answer and "R:" in answer


def test_answer_from_faq_preserves_minor_conditions_in_context(build_context):
    context = build_context({})
    answer = answer_from_faq(context, "Tengo 17 años, ¿qué necesito para participar?")
    source = next(
        entry["answer"] for entry in context.retrieved_context
        if "edad mínima" in entry["question"]
    )
    assert "16 y 17 años" in source
    assert "padres o tutores legales" in source
    assert "carta de responsabilidad" in source
    assert source in answer


def test_answer_from_faq_retrieves_clothing_for_vestirse(build_context):
    context = build_context({})
    answer = answer_from_faq(context, "vestirse para la actividad aérea")
    assert "ropa cómoda y deportiva" in answer
    assert any(
        "ropa cómoda y deportiva" in entry["answer"] for entry in context.retrieved_context
    )


def test_answer_from_faq_retrieves_camera_policy_for_gopro(build_context):
    for query in ("¿Puedo llevar mi GoPro durante el salto?", "GoPro"):
        context = build_context({})
        answer = answer_from_faq(context, query)
        policy = "no se permite llevar cámaras ni celulares personales durante el salto"
        assert policy in answer
        assert any(policy in entry["answer"] for entry in context.retrieved_context)


def test_answer_from_faq_handles_no_match(build_context):
    context = build_context({})
    answer = answer_from_faq(context, "xyzzyquantumteleportation")
    assert "No se encontro" in answer


def test_answer_from_faq_abstains_on_missing_price(build_context):
    context = build_context({})
    assert "No se encontro" in answer_from_faq(context, "¿Cuánto cuesta el salto?")


def test_answer_from_faq_includes_contact_from_informative_section(build_context):
    context = build_context({})
    answer = answer_from_faq(context, "¿Cuál es el teléfono de contacto de Parachute S.A.?")
    assert "+502 2300-0000" in answer
    assert context.retrieved_context == [
        {"question": entry.question, "answer": entry.answer}
        for entry in context.services.faq_service.search_faq("¿Cuál es el teléfono de contacto de Parachute S.A.?")
    ]
    assert answer == "\n\n".join(
        f"P: {entry['question']}\nR: {entry['answer']}" for entry in context.retrieved_context
    )


def test_evaluate_jump_day_rejects_invalid_format(build_context):
    context = build_context({})
    result = evaluate_jump_day(context, "29/09/2026")
    assert "Fecha invalida" in result
    assert context.jump_assessment is None


def test_evaluate_jump_day_stores_assessment_in_context(build_context):
    context = build_context({TOMORROW: make_snapshot(TOMORROW)})
    result = evaluate_jump_day(context, TOMORROW.isoformat())
    assert "IDEAL" in result
    assert context.jump_assessment is not None
    assert context.jump_assessment.decision == Decision.IDEAL
    assert context.requested_date == TOMORROW


def test_evaluate_jump_day_rejects_date_outside_horizon(build_context):
    context = build_context({})
    too_far = FIXED_TODAY + timedelta(days=200)
    result = evaluate_jump_day(context, too_far.isoformat())
    assert "Error" in result
    assert context.jump_assessment is None


def test_create_appointment_refused_without_prior_weather_check(build_context):
    context = build_context({})
    result = book_appointment(context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com")
    assert "primero debes ejecutar check_jump_day" in result
    assert context.appointment_record is None


def test_create_appointment_succeeds_after_ideal_weather_check(build_context):
    context = build_context({TOMORROW: make_snapshot(TOMORROW)})
    evaluate_jump_day(context, TOMORROW.isoformat())
    evaluate_availability(context, TOMORROW.isoformat())

    result = book_appointment(context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com")

    assert "Cita confirmada" in result
    assert TOMORROW.isoformat() in result
    assert context.appointment_record is not None
    assert context.availability_approved_date is None
    assert [event["tool"] for event in context.get_tool_trace()] == [
        "check_jump_day", "check_appointment_availability", "create_appointment"
    ]


def test_create_appointment_requires_approved_availability(build_context):
    context = build_context({TOMORROW: make_snapshot(TOMORROW)})
    evaluate_jump_day(context, TOMORROW.isoformat())
    refused = book_appointment(context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com")
    assert "check_appointment_availability" in refused
    assert context.appointment_record is None
    assert context.get_tool_trace()[-1]["result"]["error"] == "availability_not_approved"

    context.services.calendar_service.max_slots_per_day = 0
    assert not evaluate_availability(context, TOMORROW.isoformat()).startswith("Hay cupo")
    refused = book_appointment(context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com")
    assert "check_appointment_availability" in refused
    assert context.appointment_record is None


def test_booking_rejects_untraced_or_wrong_date_availability(build_context):
    other_day = TOMORROW + timedelta(days=1)
    context = build_context({TOMORROW: make_snapshot(TOMORROW), other_day: make_snapshot(other_day)})
    evaluate_jump_day(context, TOMORROW.isoformat())
    context.availability_approved_date = TOMORROW  # A date field alone is not authorization.
    refused = book_appointment(context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com")
    assert "check_appointment_availability" in refused
    assert context.appointment_record is None

    assert "No se puede aprobar disponibilidad" in evaluate_availability(context, other_day.isoformat())
    refused = book_appointment(context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com")
    assert "check_appointment_availability" in refused
    assert context.appointment_record is None

    evaluate_jump_day(context, other_day.isoformat())
    assert "Hay cupo" in evaluate_availability(context, other_day.isoformat())
    assert "no coincide" in book_appointment(
        context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com"
    )
    assert context.appointment_record is None


def test_new_weather_check_or_date_change_invalidates_booking_approvals(build_context):
    other_day = TOMORROW + timedelta(days=1)
    context = build_context({TOMORROW: make_snapshot(TOMORROW), other_day: make_snapshot(other_day)})
    evaluate_jump_day(context, TOMORROW.isoformat())
    evaluate_availability(context, TOMORROW.isoformat())
    assert context.has_current_booking_approvals(TOMORROW)

    evaluate_jump_day(context, other_day.isoformat())
    assert not context.has_current_booking_approvals(TOMORROW)
    assert not context.has_current_booking_approvals(other_day)
    assert "No se puede aprobar disponibilidad" in evaluate_availability(context, TOMORROW.isoformat())
    assert "no coincide" in book_appointment(
        context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com"
    )
    assert "check_appointment_availability" in book_appointment(
        context, other_day.isoformat(), "Juan Perez", "juan@example.com"
    )


def test_user_date_change_and_clock_rollover_revoke_approvals(build_context):
    other_day = TOMORROW + timedelta(days=1)
    context = build_context({TOMORROW: make_snapshot(TOMORROW), other_day: make_snapshot(other_day)})
    evaluate_jump_day(context, TOMORROW.isoformat())
    evaluate_availability(context, TOMORROW.isoformat())
    context.today = lambda: TOMORROW
    assert not context.has_current_booking_approvals(TOMORROW)
    assert "No se puede aprobar disponibilidad" in evaluate_availability(context, TOMORROW.isoformat())

    context.today = lambda: FIXED_TODAY
    evaluate_jump_day(context, TOMORROW.isoformat())
    evaluate_availability(context, TOMORROW.isoformat())
    context.observe_user_message(f"Cambia la fecha a {other_day.isoformat().replace('-', '‑')}")
    assert context.jump_assessment is None
    assert context.availability_approved_date is None
    assert "primero debes ejecutar check_jump_day" in book_appointment(
        context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com"
    )


def test_marginal_without_confirmation_cannot_approve_availability(build_context):
    context = build_context({TOMORROW: make_snapshot(TOMORROW, wind_speed_10m_kmh=25.0)})
    evaluate_jump_day(context, TOMORROW.isoformat())
    assert "No se puede aprobar disponibilidad" in evaluate_availability(context, TOMORROW.isoformat())
    assert context.availability_approved_date is None
    assert context.get_tool_trace()[-1]["status"] == "error"
    context.observe_user_message(f"Acepto tándem experimentado para {TOMORROW.isoformat()}")
    assert "Hay cupo" in evaluate_availability(context, TOMORROW.isoformat())
    assert context.has_current_booking_approvals(TOMORROW)


def test_prohibited_weather_cannot_approve_availability(build_context):
    context = build_context({TOMORROW: make_snapshot(TOMORROW, precipitation_mm=1.0)})
    evaluate_jump_day(context, TOMORROW.isoformat())
    assert "No se puede aprobar disponibilidad" in evaluate_availability(context, TOMORROW.isoformat())
    assert context.availability_approved_date is None
    assert context.get_tool_trace()[-1]["result"]["error"] == "assessment_not_approved"


def test_weather_recheck_revokes_previous_availability_approval(build_context):
    context = build_context({TOMORROW: make_snapshot(TOMORROW)})
    evaluate_jump_day(context, TOMORROW.isoformat())
    evaluate_availability(context, TOMORROW.isoformat())
    evaluate_jump_day(context, TOMORROW.isoformat())
    result = book_appointment(context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com")
    assert "check_appointment_availability" in result
    assert context.appointment_record is None


def test_create_appointment_blocked_for_prohibited_weather(build_context):
    context = build_context({TOMORROW: make_snapshot(TOMORROW, precipitation_mm=1.0)})
    evaluate_jump_day(context, TOMORROW.isoformat())

    result = book_appointment(context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com")

    assert "No se pudo crear la cita" in result
    assert context.appointment_record is None


def test_create_appointment_requires_experienced_tandem_for_marginal(build_context):
    context = build_context({TOMORROW: make_snapshot(TOMORROW, wind_speed_10m_kmh=25.0)})
    evaluate_jump_day(context, TOMORROW.isoformat())

    refused = book_appointment(context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com", is_experienced_tandem=False)
    assert "confirmar explicitamente" in refused
    assert context.appointment_record is None

    asserted_by_model_only = book_appointment(
        context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com", is_experienced_tandem=True
    )
    assert "confirmar explicitamente" in asserted_by_model_only
    assert context.appointment_record is None

    context.observe_user_message("Sí, acepto tándem experimentado para 2026-01-01")
    assert context.confirmed_tandem_date is None
    assert context.jump_assessment is None
    evaluate_jump_day(context, TOMORROW.isoformat())
    context.observe_user_message(f"Sí, acepto tándem experimentado para {TOMORROW.isoformat()}")
    evaluate_availability(context, TOMORROW.isoformat())
    confirmed = book_appointment(context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com", is_experienced_tandem=True)
    assert "Cita confirmada" in confirmed
    assert context.appointment_record is not None


def test_tandem_confirmation_is_invalidated_by_new_weather_check(build_context):
    another_day = TOMORROW + timedelta(days=1)
    context = build_context({
        TOMORROW: make_snapshot(TOMORROW, wind_speed_10m_kmh=25.0),
        another_day: make_snapshot(another_day, wind_speed_10m_kmh=25.0),
    })
    evaluate_jump_day(context, TOMORROW.isoformat())
    context.observe_user_message("Acepto tándem experimentado")
    assert context.confirmed_tandem_date == TOMORROW
    evaluate_jump_day(context, another_day.isoformat())
    assert context.confirmed_tandem_date is None
    refused = book_appointment(
        context, another_day.isoformat(), "Juan Perez", "juan@example.com", is_experienced_tandem=True
    )
    assert "confirmar explicitamente" in refused
    assert "no coincide" in book_appointment(
        context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com", is_experienced_tandem=True
    )


def test_prohibited_weather_rejects_even_with_confirmation_flag(build_context):
    context = build_context({TOMORROW: make_snapshot(TOMORROW, precipitation_mm=1.0)})
    evaluate_jump_day(context, TOMORROW.isoformat())
    context.confirmed_tandem_date = TOMORROW
    result = book_appointment(
        context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com", is_experienced_tandem=True
    )
    assert "No se pudo crear la cita" in result
    assert context.appointment_record is None


def test_user_denial_revokes_tandem_confirmation(build_context):
    context = build_context({TOMORROW: make_snapshot(TOMORROW, wind_speed_10m_kmh=25.0)})
    evaluate_jump_day(context, TOMORROW.isoformat())
    context.observe_user_message("Acepto tándem experimentado")
    context.observe_user_message("No acepto tándem experimentado")
    assert context.confirmed_tandem_date is None


def test_create_appointment_is_idempotent(build_context):
    context = build_context({TOMORROW: make_snapshot(TOMORROW)})
    evaluate_jump_day(context, TOMORROW.isoformat())

    evaluate_availability(context, TOMORROW.isoformat())
    first = book_appointment(context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com")
    evaluate_availability(context, TOMORROW.isoformat())
    second = book_appointment(context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com")

    assert context.appointment_record is not None
    first_id = context.appointment_record.id
    evaluate_availability(context, TOMORROW.isoformat())
    book_appointment(context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com")
    assert context.appointment_record.id == first_id
    assert first and second


def test_evaluate_availability_reports_no_slots_left(build_context):
    context = build_context({TOMORROW: make_snapshot(TOMORROW)})
    context.services.calendar_service.max_slots_per_day = 1
    evaluate_jump_day(context, TOMORROW.isoformat())
    evaluate_availability(context, TOMORROW.isoformat())
    book_appointment(context, TOMORROW.isoformat(), "Cliente Uno", "uno@example.com")

    result = evaluate_availability(context, TOMORROW.isoformat())
    assert "No hay cupo disponible" in result


def test_failed_new_weather_check_cannot_reuse_previous_assessment(build_context):
    other_day = TOMORROW + timedelta(days=1)
    context = build_context({TOMORROW: make_snapshot(TOMORROW)})
    assert "IDEAL" in evaluate_jump_day(context, TOMORROW.isoformat())

    class FailingClient:
        def get_weather(self, requested_date):
            raise OpenMeteoError("simulated outage")

    context.services.weather_service = WeatherService(FailingClient(), max_horizon_days=15)
    assert "Error" in evaluate_jump_day(context, other_day.isoformat())
    assert context.requested_date is None
    assert context.jump_assessment is None
    for attempted_day in (other_day, TOMORROW):
        result = book_appointment(context, attempted_day.isoformat(), "Juan Perez", "juan@example.com")
        assert "No se puede crear" in result
    assert context.services.calendar_service.check_availability(TOMORROW)


def test_booking_requires_explicit_matching_date(build_context):
    context = build_context({TOMORROW: make_snapshot(TOMORROW)})
    evaluate_jump_day(context, TOMORROW.isoformat())
    other_day = TOMORROW + timedelta(days=1)
    result = book_appointment(context, other_day.isoformat(), "Juan Perez", "juan@example.com")
    assert "no coincide" in result
    assert context.appointment_record is None


def test_invalid_new_date_clears_previous_assessment(build_context):
    context = build_context({TOMORROW: make_snapshot(TOMORROW)})
    evaluate_jump_day(context, TOMORROW.isoformat())
    assert "Fecha invalida" in evaluate_jump_day(context, "not-a-date")
    assert context.jump_assessment is None
    assert "No se puede crear" in book_appointment(
        context, TOMORROW.isoformat(), "Juan Perez", "juan@example.com"
    )


def test_out_of_range_new_date_clears_previous_assessment(build_context):
    context = build_context({TOMORROW: make_snapshot(TOMORROW)})
    evaluate_jump_day(context, TOMORROW.isoformat())
    assert "Error" in evaluate_jump_day(context, (TOMORROW + timedelta(days=30)).isoformat())
    assert context.jump_assessment is None


def test_weather_tool_uses_injected_today_at_both_horizon_boundaries(build_context):
    last_day = FIXED_TODAY + timedelta(days=15)
    context = build_context({
        FIXED_TODAY: make_snapshot(FIXED_TODAY),
        last_day: make_snapshot(last_day),
    })
    assert "IDEAL" in evaluate_jump_day(context, FIXED_TODAY.isoformat())
    assert "IDEAL" in evaluate_jump_day(context, last_day.isoformat())
    assert "ya paso" in evaluate_jump_day(context, (FIXED_TODAY - timedelta(days=1)).isoformat())
    assert "fuera del horizonte" in evaluate_jump_day(
        context, (FIXED_TODAY + timedelta(days=16)).isoformat()
    )


@pytest.mark.parametrize("raw", [" 2026-09-18 ", "2026-9-18", "2026‑09‑18"])
def test_unpadded_or_unicode_dates_flow_through_one_normalized_value(build_context, raw):
    context = build_context({TOMORROW: make_snapshot(TOMORROW)})
    assert "IDEAL" in evaluate_jump_day(context, raw)
    assert "Hay cupo" in evaluate_availability(context, raw)
    assert book_appointment(context, raw, "Juan Perez", "juan@example.com").startswith("Cita confirmada")
    assert {event["arguments"]["date_str"] for event in context.get_tool_trace()} == {TOMORROW.isoformat()}


@pytest.mark.parametrize(("name", "contact"), [("A", "un dato inválido"), ("Juan Perez", "12"), ("Ana'); DROP", "a@b.co")])
def test_booking_rejects_invalid_customer_data_in_domain(build_context, name, contact):
    context = build_context({TOMORROW: make_snapshot(TOMORROW)})
    evaluate_jump_day(context, TOMORROW.isoformat())
    evaluate_availability(context, TOMORROW.isoformat())
    result = book_appointment(context, TOMORROW.isoformat(), name, contact)
    assert result.startswith("No se pudo crear la cita")
    assert context.appointment_record is None
    assert context.get_tool_trace()[-1]["result"] == {"created": False, "error": "invalid_input"}


def test_booking_tool_reports_invalid_input_without_using_capacity(build_context):
    context = build_context({TOMORROW: make_snapshot(TOMORROW)})
    evaluate_jump_day(context, TOMORROW.isoformat())
    result = book_appointment(context, TOMORROW.isoformat(), "   ", "juan@example.com", party_size=0)
    assert "nombre" in result
    assert context.appointment_record is None
    assert context.services.calendar_service.check_availability(TOMORROW)


@pytest.mark.parametrize("model_query", ["pregnancy", "pregnant skydiving restrictions"])
def test_faq_search_falls_back_to_the_users_words_when_the_model_rephrases(build_context, model_query):
    # Regression from eval-Ufz: the specialist searched with a 9-character rephrasing and got 0 results.
    context = build_context({})
    context.observe_user_message("Estoy embarazada, ¿puedo saltar?")
    answer = answer_from_faq(context, model_query)
    assert "embarazo" in answer
    event = context.get_tool_trace()[-1]
    assert event["arguments"]["fallback_to_user_message"] is True
    assert event["result"] == {"match_count": 1}


def test_faq_search_does_not_fall_back_when_the_query_already_matches(build_context):
    context = build_context({})
    context.observe_user_message("¿Cuál es el límite de peso?")
    answer_from_faq(context, "peso máximo")
    assert context.get_tool_trace()[-1]["arguments"]["fallback_to_user_message"] is False


def test_irrelevant_question_still_abstains_after_fallback(build_context):
    context = build_context({})
    context.observe_user_message("¿Quién ganó el mundial de ajedrez de 1972?")
    assert "No se encontro" in answer_from_faq(context, "chess world champion 1972")
