"""Abstraccion de calendarizacion con una implementacion local in-memory.

El proyecto previo (Sistema-RAG) no usa ningun proveedor de calendario, por lo que
no se asume Google Calendar. Esta clase concentra las garantias anti-bypass: ninguna
implementacion de CalendarService puede crear una cita sin una evaluacion aprobada.
"""

from dataclasses import dataclass, field
from datetime import date
import threading
from typing import Protocol
import uuid

from src.domain.appointment_models import AppointmentData, AppointmentRecord
from src.domain.weather_models import Decision, JumpAssessment


class CalendarServiceError(RuntimeError):
    """La cita no pudo crearse por una regla de negocio o de disponibilidad."""


class CalendarConflictError(CalendarServiceError):
    """Ya existe una cita del mismo cliente y fecha con datos distintos."""


@dataclass(frozen=True)
class BookingOutcome:
    record: AppointmentRecord
    created: bool  # False when an identical appointment already existed


class CalendarService(Protocol):
    def check_availability(self, jump_date: date, party_size: int = 1) -> bool: ...

    def create_appointment(self, data: AppointmentData, assessment: JumpAssessment) -> BookingOutcome: ...


def _validate_party_size(party_size: int) -> None:
    if type(party_size) is not int or party_size < 1:
        raise CalendarServiceError("El numero de participantes debe ser un entero mayor o igual a 1.")


def _identical(first: AppointmentData, second: AppointmentData) -> bool:
    return (
        first.jump_date == second.jump_date and first.contact == second.contact
        and first.customer_name.casefold() == second.customer_name.casefold()
        and first.party_size == second.party_size
        and first.is_experienced_tandem == second.is_experienced_tandem
    )


@dataclass
class InMemoryCalendarService:
    # Participant places per day; it is also the largest group a single booking may hold.
    max_slots_per_day: int = 8
    _records: list[AppointmentRecord] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def booked_participants(self, jump_date: date) -> int:
        return sum(record.data.party_size for record in self._records if record.data.jump_date == jump_date)

    def check_availability(self, jump_date: date, party_size: int = 1) -> bool:
        _validate_party_size(party_size)
        with self._lock:
            return self.booked_participants(jump_date) + party_size <= self.max_slots_per_day

    def _same_customer(self, data: AppointmentData) -> AppointmentRecord | None:
        name = data.customer_name.casefold()
        return next(
            (
                record for record in self._records
                if record.data.jump_date == data.jump_date
                and (record.data.contact == data.contact or record.data.customer_name.casefold() == name)
            ),
            None,
        )

    def create_appointment(self, data: AppointmentData, assessment: JumpAssessment) -> BookingOutcome:
        """Create atomically when weather and capacity allow; identical repeats are not duplicated."""
        if assessment.weather is None or assessment.weather.date != data.jump_date:
            raise CalendarServiceError(
                "La evaluacion meteorologica no corresponde a la fecha de la cita solicitada."
            )
        if assessment.decision == Decision.PROHIBITED:
            raise CalendarServiceError(
                "No se puede crear la cita: las condiciones climaticas estan prohibidas para saltar."
            )
        if assessment.decision == Decision.MARGINAL and not data.is_experienced_tandem:
            raise CalendarServiceError(
                "Condiciones marginales: solo se permite tandem experimentado. "
                "Confirma esta condicion antes de calendarizar."
            )
        _validate_party_size(data.party_size)
        if data.party_size > self.max_slots_per_day:
            raise CalendarServiceError(
                f"El grupo excede la capacidad maxima de {self.max_slots_per_day} participantes por dia."
            )

        with self._lock:
            existing = self._same_customer(data)
            if existing is not None:
                if _identical(existing.data, data):
                    return BookingOutcome(record=existing, created=False)
                raise CalendarConflictError(
                    "Ya existe una cita de este cliente para esa fecha con datos distintos "
                    "(participantes, contacto, nombre o modalidad tandem); no se modifico."
                )
            if self.booked_participants(data.jump_date) + data.party_size > self.max_slots_per_day:
                raise CalendarServiceError(f"No hay cupo disponible para {data.jump_date.isoformat()}.")
            record = AppointmentRecord(id=str(uuid.uuid4()), data=data, assessment=assessment)
            self._records.append(record)
            return BookingOutcome(record=record, created=True)
