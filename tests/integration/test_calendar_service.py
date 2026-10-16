from datetime import date

import pytest

from src.domain.appointment_models import AppointmentData
from src.domain.weather_models import Decision, JumpAssessment, WeatherSnapshot
from src.services.calendar_service import CalendarServiceError, InMemoryCalendarService

JUMP_DATE = date(2026, 9, 29)


def make_weather(**overrides) -> WeatherSnapshot:
    values = dict(
        date=JUMP_DATE,
        wind_speed_10m_kmh=10.0,
        wind_gust_10m_kmh=10.0,
        precipitation_mm=0.0,
        cloud_cover_percent=10.0,
        temperature_2m_c=25.0,
    )
    values.update(overrides)
    return WeatherSnapshot(**values)


def make_assessment(decision: Decision, weather: WeatherSnapshot | None = None) -> JumpAssessment:
    return JumpAssessment(decision=decision, weather=weather or make_weather())


def make_data(**overrides) -> AppointmentData:
    values = dict(
        customer_name="Juan Perez",
        contact="juan@example.com",
        jump_date=JUMP_DATE,
        is_experienced_tandem=False,
    )
    values.update(overrides)
    return AppointmentData(**values)


def test_check_availability_true_when_no_bookings():
    service = InMemoryCalendarService()
    assert service.check_availability(JUMP_DATE) is True


def test_create_appointment_succeeds_for_ideal_assessment():
    service = InMemoryCalendarService()
    record = service.create_appointment(make_data(), make_assessment(Decision.IDEAL)).record
    assert record.data.customer_name == "Juan Perez"
    assert record.assessment.decision == Decision.IDEAL


def test_create_appointment_never_created_for_prohibited():
    service = InMemoryCalendarService()
    with pytest.raises(CalendarServiceError):
        service.create_appointment(make_data(), make_assessment(Decision.PROHIBITED))
    assert service.check_availability(JUMP_DATE) is True


def test_create_appointment_requires_experienced_tandem_for_marginal():
    service = InMemoryCalendarService()
    with pytest.raises(CalendarServiceError):
        service.create_appointment(
            make_data(is_experienced_tandem=False), make_assessment(Decision.MARGINAL)
        )


def test_create_appointment_succeeds_for_marginal_with_experienced_tandem():
    service = InMemoryCalendarService()
    record = service.create_appointment(
        make_data(is_experienced_tandem=True), make_assessment(Decision.MARGINAL)
    ).record
    assert record.assessment.decision == Decision.MARGINAL


def test_create_appointment_rejects_mismatched_assessment_date():
    service = InMemoryCalendarService()
    other_day_weather = make_weather(date=date(2026, 10, 1))
    with pytest.raises(CalendarServiceError):
        service.create_appointment(make_data(), make_assessment(Decision.IDEAL, other_day_weather))


def test_create_appointment_is_idempotent_for_same_customer_and_date():
    service = InMemoryCalendarService()
    assessment = make_assessment(Decision.IDEAL)
    first = service.create_appointment(make_data(), assessment).record
    second = service.create_appointment(make_data(), assessment)
    assert second.created is False and first.id == second.record.id


def test_create_appointment_fails_when_no_slots_left():
    service = InMemoryCalendarService(max_slots_per_day=1)
    assessment = make_assessment(Decision.IDEAL)
    service.create_appointment(make_data(customer_name="Cliente Uno", contact="uno@example.com"), assessment)
    with pytest.raises(CalendarServiceError):
        service.create_appointment(make_data(customer_name="Cliente Dos", contact="dos@example.com"), assessment)


@pytest.mark.parametrize(
    "overrides",
    [
        {"customer_name": ""},
        {"customer_name": "   "},
        {"customer_name": None},
        {"customer_name": 123},
        {"customer_name": "A" * 201},
        {"contact": ""},
        {"contact": "   "},
        {"contact": None},
        {"contact": 123},
        {"contact": "a" * 255},
        {"jump_date": None},
        {"jump_date": "2026-09-29"},
        {"party_size": 0},
        {"party_size": -1},
        {"party_size": True},
        {"party_size": "2"},
        {"is_experienced_tandem": "true"},
    ],
)
def test_invalid_appointment_data_is_rejected_without_using_capacity(overrides):
    service = InMemoryCalendarService()
    with pytest.raises(ValueError):
        service.create_appointment(make_data(**overrides), make_assessment(Decision.IDEAL))
    assert service.check_availability(JUMP_DATE)


def test_appointment_data_accepts_boundary_lengths_and_minimum_party_size():
    data = make_data(customer_name="A" * 200, contact="c" * 240 + "@example.com", party_size=1)
    record = InMemoryCalendarService().create_appointment(data, make_assessment(Decision.IDEAL)).record
    assert record.data == data
