"""Participant capacity, duplicates and faithful traces (AUD-011, AUD-012)."""

from datetime import timedelta

import pytest

from src.domain.appointment_models import AppointmentData
from src.domain.weather_models import Decision, JumpAssessment
from src.services.calendar_service import (
    CalendarConflictError, CalendarServiceError, InMemoryCalendarService,
)
from src.tools.calendar_tools import book_appointment, evaluate_availability
from src.tools.weather_tools import evaluate_jump_day
from tests.agents.conftest import FIXED_TODAY, make_snapshot

DAY = FIXED_TODAY + timedelta(days=3)
ISO = DAY.isoformat()


def _assessment():
    return JumpAssessment(decision=Decision.IDEAL, weather=make_snapshot(DAY))


def _data(name="Ana Ejemplo", contact="ana@example.com", party_size=1, tandem=False):
    return AppointmentData(name, contact, DAY, tandem, party_size)


def test_capacity_is_consumed_by_participants_not_records():
    calendar = InMemoryCalendarService(max_slots_per_day=8)
    calendar.create_appointment(_data(party_size=5), _assessment())
    assert calendar.booked_participants(DAY) == 5
    assert calendar.check_availability(DAY, 3) is True
    assert calendar.check_availability(DAY, 4) is False
    with pytest.raises(CalendarServiceError, match="No hay cupo"):
        calendar.create_appointment(_data("Beto Prueba", "beto@example.com", party_size=4), _assessment())
    calendar.create_appointment(_data("Beto Prueba", "beto@example.com", party_size=3), _assessment())
    assert calendar.check_availability(DAY, 1) is False  # exhausted


def test_group_larger_than_daily_capacity_is_rejected():
    calendar = InMemoryCalendarService(max_slots_per_day=8)
    assert calendar.check_availability(DAY, 9) is False
    with pytest.raises(CalendarServiceError, match="capacidad maxima de 8"):
        calendar.create_appointment(_data(party_size=9), _assessment())
    assert calendar.booked_participants(DAY) == 0


@pytest.mark.parametrize("party_size", [0, -1, True, "2"])
def test_invalid_party_size_in_availability(party_size):
    with pytest.raises(CalendarServiceError):
        InMemoryCalendarService().check_availability(DAY, party_size)


def test_identical_duplicate_is_reported_and_not_stored_twice():
    calendar = InMemoryCalendarService()
    first = calendar.create_appointment(_data(), _assessment())
    again = calendar.create_appointment(_data(name="ana  ejemplo", contact="ANA@example.com"), _assessment())
    assert first.created is True and again.created is False
    assert again.record.id == first.record.id
    assert calendar.booked_participants(DAY) == 1


@pytest.mark.parametrize("changes", [
    {"party_size": 2}, {"tandem": True}, {"contact": "otra@example.com"}, {"name": "Ana Distinta"},
])
def test_changed_duplicate_is_a_conflict_and_nothing_is_overwritten(changes):
    calendar = InMemoryCalendarService()
    calendar.create_appointment(_data(), _assessment())
    with pytest.raises(CalendarConflictError):
        calendar.create_appointment(_data(**changes), _assessment())
    assert calendar.booked_participants(DAY) == 1


def _approved(build_context, party_size=1, **kwargs):
    context = build_context({DAY: make_snapshot(DAY)})
    for name, value in kwargs.items():
        setattr(context.services.calendar_service, name, value)
    evaluate_jump_day(context, ISO)
    evaluate_availability(context, ISO, party_size)
    return context


def test_trace_marks_created_only_for_new_records(build_context):
    context = _approved(build_context, 2)
    assert book_appointment(context, ISO, "Ana Ejemplo", "ana@example.com", party_size=2).startswith("Cita confirmada")
    evaluate_availability(context, ISO, 2)
    duplicate = book_appointment(context, ISO, "Ana Ejemplo", "ana@example.com", party_size=2)
    assert duplicate.startswith("Ya existia una cita identica")
    first, second = [event for event in context.get_tool_trace() if event["tool"] == "create_appointment"]
    assert first["result"] == {"created": True, "date": ISO}
    assert second["result"] == {"created": False, "duplicate": True, "date": ISO}
    assert len(context.appointments) == 1


def test_trace_marks_conflict_when_data_changes(build_context):
    context = _approved(build_context, 1)
    book_appointment(context, ISO, "Ana Ejemplo", "ana@example.com", party_size=1)
    evaluate_availability(context, ISO, 4)
    result = book_appointment(context, ISO, "Ana Ejemplo", "ana@example.com", party_size=4)
    assert "datos distintos" in result
    event = context.get_tool_trace()[-1]
    assert event["status"] == "error"
    assert event["result"] == {"created": False, "duplicate": True, "error": "conflict"}
    assert context.appointment_record.data.party_size == 1


def test_availability_is_bound_to_the_group_size(build_context):
    context = _approved(build_context, 2)
    result = book_appointment(context, ISO, "Ana Ejemplo", "ana@example.com", party_size=5)
    assert "numero de participantes" in result
    assert context.get_tool_trace()[-1]["result"]["error"] == "availability_not_approved"


def test_availability_reports_group_too_large(build_context):
    context = build_context({DAY: make_snapshot(DAY)})
    evaluate_jump_day(context, ISO)
    assert "excede la capacidad maxima de 8" in evaluate_availability(context, ISO, 9)
    assert context.get_tool_trace()[-1]["result"] == {"available": False}
    assert context.get_tool_trace()[-1]["arguments"]["party_size"] == 9
