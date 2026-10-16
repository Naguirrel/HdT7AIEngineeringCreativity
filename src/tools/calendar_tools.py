"""Tools compartidos de calendarizacion. No permiten crear una cita sin evaluacion valida.

La logica vive en funciones planas (`evaluate_availability`, `book_appointment`)
testeables sin el runtime de agentes; los decoradores @function_tool solo las
conectan al contexto de la conversacion.
"""


from agents import RunContextWrapper, function_tool

from src.agents.common.context import ParachuteContext, records_output
from src.domain.appointment_models import AppointmentData, AppointmentRecord, normalize_contact
from src.domain.dates import normalized_date_or_none, parse_date_argument
from src.domain.weather_models import Decision
from src.observability import log_event
from src.services.calendar_service import CalendarConflictError, CalendarServiceError


def contact_identity(contact: object) -> object:
    """Canonical contact used for pseudonyms, so '5555 1234' and '+50255551234' match."""
    try:
        return normalize_contact(contact)
    except ValueError:
        return contact


def _requested_party_size(context: ParachuteContext, party_size: int | None) -> int | None:
    if party_size is None:
        stored = context.booking_request.party_size
        return stored if stored is not None else 1
    return party_size


@records_output
def evaluate_availability(context: ParachuteContext, date_str: str, party_size: int | None = None) -> str:
    context.availability_approved_date = None
    party_size = _requested_party_size(context, party_size)
    trace_args = {
        "date_str": normalized_date_or_none(date_str),
        "party_size": party_size if type(party_size) is int else None,
    }
    if type(party_size) is not int or party_size < 1:
        context.record_tool_event("check_appointment_availability", trace_args, {"error": "invalid_party_size"}, "error")
        return "El numero de participantes debe ser un entero mayor o igual a 1."
    try:
        parsed_date = parse_date_argument(date_str)
    except ValueError as error:
        context.record_tool_event("check_appointment_availability", trace_args, {"error": "invalid_date_format"}, "error")
        return f"Fecha invalida: {error}"

    assessment = context.jump_assessment
    if (
        assessment is None or context.requested_date != parsed_date
        or context.assessment_checked_on != context.today()
        or assessment.weather is None or assessment.weather.date != parsed_date
        or not assessment.allows_appointment
        or (assessment.requires_experienced_tandem and context.confirmed_tandem_date != parsed_date)
    ):
        context.record_tool_event(
            "check_appointment_availability", trace_args, {"error": "assessment_not_approved"}, "error"
        )
        return "No se puede aprobar disponibilidad: primero valida el clima y los requisitos para esta fecha."

    calendar = context.services.calendar_service
    try:
        available = calendar.check_availability(parsed_date, party_size)
    except CalendarServiceError as error:
        context.record_tool_event("check_appointment_availability", trace_args, {"error": "availability_failed"}, "error")
        return f"No se pudo comprobar disponibilidad: {error}"
    context.record_tool_event("check_appointment_availability", trace_args, {"available": available}, "success")
    if available:
        context.availability_approved_date = parsed_date
        return f"Hay cupo disponible para {party_size} participante(s) el {parsed_date.isoformat()}."
    capacity = getattr(calendar, "max_slots_per_day", None)
    if capacity is not None and party_size > capacity:
        return f"El grupo de {party_size} excede la capacidad maxima de {capacity} participantes por dia."
    return f"No hay cupo disponible para {party_size} participante(s) el {parsed_date.isoformat()}."


def format_confirmation(record: AppointmentRecord) -> str:
    """User-facing confirmation derived only from the stored record."""
    modality = "tandem con instructor experimentado" if record.data.is_experienced_tandem else "estandar"
    return (
        f"Cita confirmada (id={record.id}) para {record.data.jump_date.isoformat()}; "
        f"participantes: {record.data.party_size}; modalidad: {modality}."
    )


@records_output
def book_appointment(
    context: ParachuteContext,
    date_str: str,
    customer_name: str = "",
    contact: str = "",
    is_experienced_tandem: bool = False,
    party_size: int | None = None,
) -> str:
    # Specialists reached through as_tool() may not receive the user's data; use what the
    # user already provided in this session instead of asking again.
    stored = context.booking_request
    if not (isinstance(customer_name, str) and customer_name.strip()) and stored.customer_name:
        customer_name = stored.customer_name
    if not (isinstance(contact, str) and contact.strip()) and stored.contact:
        contact = stored.contact
    if party_size is None:
        party_size = stored.party_size if stored.party_size is not None else 1
    log_event(architecture=context.architecture, tool="create_appointment", calendar_write_attempt=1)
    trace_args = {
        "date_str": normalized_date_or_none(date_str),
        "customer_name_provided": isinstance(customer_name, str) and bool(customer_name.strip()),
        "contact_provided": isinstance(contact, str) and bool(contact.strip()),
        # Keyed per session (HMAC); never plain or static hashes of personal data.
        "customer_name_hmac": context.pseudonymize(customer_name),
        "contact_hmac": context.pseudonymize(contact_identity(contact)),
        "is_experienced_tandem": is_experienced_tandem if type(is_experienced_tandem) is bool else None,
        "party_size": party_size if type(party_size) is int else None,
    }

    if context.jump_assessment is None or context.requested_date is None:
        log_event(architecture=context.architecture, tool="create_appointment", calendar_write_result="refused_no_assessment")
        context.record_tool_event("create_appointment", trace_args, {"created": False, "error": "no_assessment"}, "error")
        return (
            "No se puede crear la cita: primero debes ejecutar check_jump_day para la fecha "
            "deseada y obtener una evaluacion valida."
        )

    try:
        requested_date = parse_date_argument(date_str)
    except ValueError as error:
        context.record_tool_event("create_appointment", trace_args, {"created": False, "error": "invalid_date_format"}, "error")
        return f"Fecha invalida: {error}"

    assessed_weather = context.jump_assessment.weather
    if (
        requested_date != context.requested_date
        or assessed_weather is None
        or assessed_weather.date != requested_date
    ):
        context.record_tool_event("create_appointment", trace_args, {"created": False, "error": "assessment_date_mismatch"}, "error")
        return "No se puede crear la cita: la fecha solicitada no coincide con la evaluacion meteorologica vigente."

    if context.jump_assessment.decision == Decision.MARGINAL and (
        not is_experienced_tandem or context.confirmed_tandem_date != requested_date
    ):
        context.record_tool_event("create_appointment", trace_args, {"created": False, "error": "missing_tandem_confirmation"}, "error")
        return (
            "No se puede crear la cita: el usuario debe confirmar explicitamente "
            "el tandem experimentado para esta fecha."
        )

    if not context.jump_assessment.allows_appointment:
        context.record_tool_event("create_appointment", trace_args, {"created": False, "error": "weather_prohibited"}, "error")
        return "No se pudo crear la cita: las condiciones climaticas prohiben el salto."

    try:
        data = AppointmentData(
            customer_name=customer_name,
            contact=contact,
            jump_date=requested_date,
            is_experienced_tandem=is_experienced_tandem,
            party_size=party_size,
        )
    except ValueError as error:
        log_event(architecture=context.architecture, tool="create_appointment", calendar_write_result="invalid_input")
        context.record_tool_event("create_appointment", trace_args, {"created": False, "error": "invalid_input"}, "error")
        return f"No se pudo crear la cita: {error}"

    if not context.has_current_booking_approvals(requested_date, data.party_size):
        context.record_tool_event("create_appointment", trace_args, {"created": False, "error": "availability_not_approved"}, "error")
        return (
            "No se puede crear la cita: primero debes ejecutar check_appointment_availability para esta "
            "fecha y este numero de participantes y confirmar que hay cupo."
        )

    context.availability_approved_date = None

    try:
        outcome = context.services.calendar_service.create_appointment(data, context.jump_assessment)
    except CalendarConflictError as error:
        log_event(architecture=context.architecture, tool="create_appointment", calendar_write_result="conflict")
        context.record_tool_event(
            "create_appointment", trace_args, {"created": False, "duplicate": True, "error": "conflict"}, "error"
        )
        return f"No se pudo crear la cita: {error}"
    except CalendarServiceError as error:
        log_event(architecture=context.architecture, tool="create_appointment", calendar_write_result="rejected")
        context.record_tool_event("create_appointment", trace_args, {"created": False, "error": "calendar_rejected"}, "error")
        return f"No se pudo crear la cita: {error}"

    record = outcome.record
    context.appointment_data = record.data
    context.appointment_record = record
    if record not in context.appointments:
        context.appointments.append(record)
    context.remember_booking_details(
        jump_date=record.data.jump_date, customer_name=record.data.customer_name,
        contact=record.data.contact, party_size=record.data.party_size,
    )
    if outcome.created:
        confirmation = format_confirmation(record)
        result = {"created": True, "date": requested_date.isoformat()}
    else:
        confirmation = (
            f"Ya existia una cita identica (id={record.id}) para {record.data.jump_date.isoformat()}; "
            "no se creo una nueva."
        )
        result = {"created": False, "duplicate": True, "date": requested_date.isoformat()}
    context.appointment_confirmation = confirmation
    log_event(architecture=context.architecture, tool="create_appointment",
              calendar_write_result="success" if outcome.created else "duplicate")
    context.record_tool_event("create_appointment", trace_args, result, "success")
    return confirmation


@function_tool
def check_appointment_availability(
    wrapper: RunContextWrapper[ParachuteContext], date_str: str, party_size: int | None = None
) -> str:
    """Verifica si hay cupo disponible para todo el grupo en una fecha.

    Args:
        date_str: fecha a verificar en formato YYYY-MM-DD.
        party_size: numero de participantes; si se omite se usa el indicado por el usuario.
    """
    return evaluate_availability(wrapper.context, date_str, party_size)


@function_tool
def create_appointment(
    wrapper: RunContextWrapper[ParachuteContext],
    date_str: str,
    customer_name: str = "",
    contact: str = "",
    is_experienced_tandem: bool = False,
    party_size: int | None = None,
) -> str:
    """Crea la cita de salto para la fecha previamente verificada con check_jump_day.

    Args:
        date_str: fecha solicitada en formato YYYY-MM-DD; debe coincidir con la evaluacion vigente.
        customer_name: nombre completo del cliente; si se omite se usa el ya proporcionado por el usuario.
        contact: telefono o correo del cliente; si se omite se usa el ya proporcionado por el usuario.
        is_experienced_tandem: True si el cliente confirma que acepta un tandem experimentado
            (obligatorio para fechas con evaluacion MARGINAL).
        party_size: numero de personas que saltan juntas; si se omite se usa el indicado por el usuario.
    """
    return book_appointment(wrapper.context, date_str, customer_name, contact, is_experienced_tandem, party_size)
