"""Deterministic in-memory calendars, optionally preloaded with earlier bookings."""

from datetime import date
import json
from pathlib import Path

from evals.fixtures.weather import FixtureError
from src.domain.appointment_models import AppointmentData
from src.domain.weather_models import Decision, JumpAssessment, WeatherSnapshot
from src.services.calendar_service import InMemoryCalendarService


def make_calendar_service(name: str) -> InMemoryCalendarService:
    fixtures = json.loads(Path(__file__).with_name("calendar.json").read_text(encoding="utf-8"))
    if name not in fixtures:
        raise FixtureError(f"Fixture de calendario desconocido: {name}")
    calendar = InMemoryCalendarService()
    for day_text, participants in fixtures[name].items():
        day = date.fromisoformat(day_text)
        weather = WeatherSnapshot(day, 10.0, 15.0, 0.0, 10.0, 25.0, source="fixture")
        assessment = JumpAssessment(decision=Decision.IDEAL, weather=weather)
        # One booking per participant, through the public API, with synthetic customers.
        for index in range(participants):
            calendar.create_appointment(
                AppointmentData(f"Reserva Previa {chr(65 + index)}", f"+5020000{index:04d}", day), assessment
            )
    return calendar
