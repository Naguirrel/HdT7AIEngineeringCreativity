"""Estado/contexto tipado compartido por las tres arquitecturas de agentes.

Sobrevive a llamadas a subagentes, as_tool() y handoffs porque el SDK propaga el
mismo objeto de contexto (RunContextWrapper[ParachuteContext]) a lo largo de todo
el run, sin depender de que el LLM recuerde datos en texto libre.
"""

from dataclasses import dataclass, field
from copy import deepcopy
from datetime import date
import functools
import hashlib
import hmac
import re
import secrets
from typing import Callable

from src.agents.common.user_message import extract_booking_details, normalize_text
from src.domain.appointment_models import AppointmentRecord, normalize_contact
from src.domain.clock import current_guatemala_date
from src.domain.weather_models import JumpAssessment
from src.services.calendar_service import CalendarService
from src.services.faq_service import FaqService
from src.services.weather_service import WeatherService


def records_output(tool_function):
    """Keep each business tool's text output as a trusted source for this turn's answer."""

    @functools.wraps(tool_function)
    def wrapper(context, *args, **kwargs):
        output = tool_function(context, *args, **kwargs)
        context.turn_tool_outputs.append(output)
        return output

    return wrapper


@dataclass
class SharedServices:
    weather_service: WeatherService
    calendar_service: CalendarService
    faq_service: FaqService


@dataclass
class BookingRequest:
    """Datos de reserva aportados por el usuario; se conservan entre turnos y as_tool()."""

    jump_date: date | None = None
    customer_name: str | None = None
    contact: str | None = None
    party_size: int | None = None
    requested: bool = False
    blocked_reason: str | None = None

    def missing_fields(self) -> list[str]:
        missing = []
        if self.jump_date is None:
            missing.append("fecha")
        if not self.customer_name:
            missing.append("nombre")
        if not self.contact:
            missing.append("contacto")
        return missing


@dataclass
class ParachuteContext:
    services: SharedServices
    architecture: str = "unknown"
    today: Callable[[], date] = field(default=current_guatemala_date, repr=False)
    requested_date: date | None = None
    jump_assessment: JumpAssessment | None = None
    assessment_checked_on: date | None = None
    availability_approved_date: date | None = None
    appointment_data: object | None = None
    appointment_record: AppointmentRecord | None = None
    appointment_confirmation: str | None = None
    confirmed_tandem_date: date | None = None
    booking_request: BookingRequest = field(default_factory=BookingRequest)
    appointments: list[AppointmentRecord] = field(default_factory=list)
    retrieved_context: list[dict[str, str]] = field(default_factory=list)
    turn_faq_entries: list[dict[str, str]] = field(default_factory=list)
    turn_tool_outputs: list[str] = field(default_factory=list)
    turn_tools: list[str] = field(default_factory=list)
    user_messages: list[str] = field(default_factory=list)
    last_user_message: str = ""
    _tool_trace: list[dict] = field(default_factory=list, repr=False)
    # Ephemeral per-session key: pseudonyms cannot be reversed by dictionary attacks
    # or compared across sessions/runs, and the key is never stored or exported.
    _trace_key: bytes = field(default_factory=lambda: secrets.token_bytes(32), repr=False)

    def pseudonymize(self, value: object) -> str | None:
        """HMAC-SHA256 of a normalized personal value, valid only inside this session."""
        if not isinstance(value, str) or not value.strip():
            return None
        normalized = " ".join(value.split()).casefold()
        return hmac.new(self._trace_key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()

    def record_tool_event(self, tool: str, arguments: dict, result: dict, status: str) -> None:
        if status not in {"success", "error"}:
            raise ValueError("El estado de la herramienta debe ser success o error.")
        self.turn_tools.append(tool)
        self._tool_trace.append({
            "sequence": len(self._tool_trace) + 1,
            "tool": tool,
            "arguments": deepcopy(arguments),
            "result": deepcopy(result),
            "status": status,
        })

    def get_tool_trace(self) -> list[dict]:
        """Return a copy so callers cannot alter the session's recorded events."""
        return deepcopy(self._tool_trace)

    def get_retrieved_context(self) -> list[dict[str, str]]:
        return deepcopy(self.retrieved_context)

    def record_faq_entries(self, entries: list[dict[str, str]]) -> None:
        self.retrieved_context.extend(deepcopy(entries))
        self.turn_faq_entries.extend(deepcopy(entries))

    def has_current_booking_approvals(self, requested_date: date, party_size: int | None = None) -> bool:
        """Require matching, ordered approvals (same date and group size) in this session's trace."""
        if self.requested_date != requested_date or self.availability_approved_date != requested_date:
            return False
        if (
            self.jump_assessment is None or not self.jump_assessment.allows_appointment
            or self.assessment_checked_on != self.today()
        ):
            return False
        weather = self.jump_assessment.weather
        if weather is None or weather.date != requested_date:
            return False
        if self.jump_assessment.requires_experienced_tandem and self.confirmed_tandem_date != requested_date:
            return False

        weather_event = next(
            (event for event in reversed(self._tool_trace) if event["tool"] == "check_jump_day"), None
        )
        availability_event = next(
            (event for event in reversed(self._tool_trace) if event["tool"] == "check_appointment_availability"), None
        )
        return bool(
            weather_event and availability_event
            and weather_event["status"] == availability_event["status"] == "success"
            and weather_event["arguments"].get("date_str") == requested_date.isoformat()
            and weather_event["result"].get("decision") == self.jump_assessment.decision.value
            and availability_event["arguments"].get("date_str") == requested_date.isoformat()
            and availability_event["result"].get("available") is True
            and (party_size is None or availability_event["arguments"].get("party_size") == party_size)
            and weather_event["sequence"] < availability_event["sequence"]
        )

    def remember_booking_details(
        self,
        *,
        jump_date: date | None = None,
        customer_name: str | None = None,
        contact: str | None = None,
        party_size: int | None = None,
        requested: bool = False,
    ) -> None:
        request = self.booking_request
        changed = False
        for name, value in (
            ("jump_date", jump_date), ("customer_name", customer_name),
            ("contact", contact), ("party_size", party_size),
        ):
            if value is not None and getattr(request, name) != value:
                setattr(request, name, value)
                changed = True
        if requested:
            request.requested = True
        if changed:
            request.blocked_reason = None

    def booking_already_recorded(self) -> bool:
        request = self.booking_request
        try:
            contact = normalize_contact(request.contact)
        except ValueError:
            return False
        return any(
            record.data.jump_date == request.jump_date and record.data.contact == contact
            for record in self.appointments
        )

    def observe_user_message(self, message: str) -> None:
        """Start a turn: keep user-provided data and handle date changes and tandem replies."""
        self.appointment_confirmation = None
        self.turn_faq_entries = []
        self.turn_tool_outputs = []
        self.turn_tools = []
        self.last_user_message = message
        self.user_messages.append(message)

        details = extract_booking_details(message, self.today())
        single_date = details.dates[0] if len(set(details.dates)) == 1 else None
        self.remember_booking_details(
            jump_date=single_date,
            customer_name=details.customer_name,
            contact=details.contact,
            party_size=details.party_size,
            requested=details.booking_intent,
        )

        if self.requested_date is None or self.jump_assessment is None:
            return
        if any(value != self.requested_date for value in details.dates):
            self.requested_date = None
            self.jump_assessment = None
            self.assessment_checked_on = None
            self.availability_approved_date = None
            self.confirmed_tandem_date = None
            return
        if not self.jump_assessment.requires_experienced_tandem:
            return

        normalized = normalize_text(message)
        if re.search(r"\b(?:no\s+(?:acepto|confirmo|quiero|deseo|estoy)|rechazo|nunca|prefiero no)\b", normalized) \
                or re.search(r"\bsin\s+(?:el\s+)?tandem\b", normalized):
            self.confirmed_tandem_date = None
            self.availability_approved_date = None
            return
        if "?" in normalized or details.ambiguous_date:
            return
        accepts = re.match(
            r"^\s*(?:(?:si|ok|vale|claro|perfecto|listo|de acuerdo)[,.!\s]+)*(?:acepto|confirmo|estoy de acuerdo)\b",
            normalized,
        )
        if accepts and "tandem" in normalized and re.search(r"\bexperimentad[oa]s?\b", normalized):
            self.confirmed_tandem_date = self.requested_date
