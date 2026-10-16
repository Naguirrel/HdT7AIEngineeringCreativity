"""Finish bookings from trusted tool state and keep the final answer truthful.

The model decides when to talk to the user, but whether an appointment exists is decided
only by the calendar. Once weather, tandem confirmation (if MARGINAL), availability and
the user's data are all in place, the booking is completed with the real business tools.
"""

import re

from agents import FunctionToolResult, RunContextWrapper, ToolsToFinalOutputResult

from src.agents.common.context import ParachuteContext
from src.agents.common.grounding import ground_answer
from src.agents.common.truthfulness import (
    enforce_consistent_eligibility, enforce_truthful_booking_claims, ensure_weather_reasons,
)
from src.agents.common.user_message import normalize_text
from src.tools.calendar_tools import book_appointment, evaluate_availability
from src.tools.faq_tools import answer_from_faq

# Tool names (business tools and as_tool() wrappers) that belong to the scheduling step.
SCHEDULING_TOOL_NAMES = {
    "check_appointment_availability", "create_appointment", "scheduling_specialist", "booking_manager",
}


def complete_pending_booking(context: ParachuteContext) -> str | None:
    """Create the requested appointment when every precondition is already satisfied."""
    if context.appointment_confirmation:
        return context.appointment_confirmation
    request = context.booking_request
    target = context.requested_date
    if (
        not request.requested or target is None or request.jump_date != target
        or request.missing_fields() or request.blocked_reason or context.booking_already_recorded()
    ):
        return None
    assessment = context.jump_assessment
    if assessment is None or not assessment.allows_appointment or context.assessment_checked_on != context.today():
        return None
    tandem = assessment.requires_experienced_tandem
    if tandem and context.confirmed_tandem_date != target:
        return None

    party_size = request.party_size if request.party_size is not None else 1
    if not context.has_current_booking_approvals(target, party_size):
        availability = evaluate_availability(context, target.isoformat(), party_size)
        if not context.has_current_booking_approvals(target, party_size):
            request.blocked_reason = availability
            return None
    outcome = book_appointment(
        context, target.isoformat(), request.customer_name, request.contact, tandem, party_size,
    )
    if not context.appointment_confirmation:
        request.blocked_reason = outcome
    return context.appointment_confirmation


_CLAUSE_SPLIT = re.compile(r",|;|\.\s|\b(?:y|ademas|tambien)\b")
_QUESTION_CUE = re.compile(
    r"\?|\b(?:que|cual|cuales|como|donde|cuando|cuanto|dime|indica|indicame|explica|explicame|"
    r"informa|necesito saber|debo llevar|puedo llevar)\b"
)
_BOOKING_WORDS = re.compile(r"\b(?:reserv\w*|agend\w*|cita|confirm\w*|acepto|tandem|personas?|somos)\b")


def _secondary_question(message: str) -> str:
    """Non-booking clauses that ask for information, e.g. "... y dime que ropa llevar"."""
    clauses = []
    for clause in _CLAUSE_SPLIT.split(normalize_text(message)):
        clause = clause.strip()
        if (
            clause and _QUESTION_CUE.search(clause) and not _BOOKING_WORDS.search(clause)
            and "@" not in clause and not re.search(r"\d{3,}", clause)
        ):
            clauses.append(clause)
    return " ".join(clauses)


def _faq_answers_for_turn(context: ParachuteContext) -> list[str]:
    if not context.turn_faq_entries:
        question = _secondary_question(context.last_user_message)
        if question:
            answer_from_faq(context, question)  # real, traced search_faq call
    answers: list[str] = []
    for entry in context.turn_faq_entries:
        if entry["answer"] not in answers:
            answers.append(entry["answer"])
    return answers


def compose_booking_answer(context: ParachuteContext) -> str:
    """Record-derived confirmation plus, for combined requests, the grounded FAQ text."""
    confirmation = context.appointment_confirmation
    answers = _faq_answers_for_turn(context)
    if not answers:
        return confirmation
    return confirmation + "\n\nAdemas, segun las FAQ oficiales de Parachute S.A.:\n" + "\n\n".join(answers)


def booking_result_or_continue(
    wrapper: RunContextWrapper[ParachuteContext], tool_results: list[FunctionToolResult]
) -> ToolsToFinalOutputResult:
    """tool_use_behavior: end the run with the record-derived confirmation after a booking step."""
    if any(result.tool.name in SCHEDULING_TOOL_NAMES for result in tool_results):
        if complete_pending_booking(wrapper.context):
            return ToolsToFinalOutputResult(
                is_final_output=True, final_output=compose_booking_answer(wrapper.context)
            )
    return ToolsToFinalOutputResult(is_final_output=False, final_output=None)


def finish_turn(context: ParachuteContext, model_output: object) -> str:
    """Single exit point for CLI, evaluation and smoke test answers."""
    complete_pending_booking(context)
    if context.appointment_confirmation:
        return compose_booking_answer(context)
    text = model_output if isinstance(model_output, str) else ""
    text = enforce_consistent_eligibility(context, ground_answer(context, text))
    text = ensure_weather_reasons(context, text)
    return enforce_truthful_booking_claims(context, text)
