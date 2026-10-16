"""Tandem confirmations are bound to the dates the user actually wrote (AUD-003)."""

from datetime import date

import pytest

from src.agents.common.user_message import extract_dates
from src.tools.weather_tools import evaluate_jump_day
from tests.agents.conftest import FIXED_TODAY, make_snapshot

EVALUATED = date(2026, 9, 20)


@pytest.mark.parametrize(("text", "expected"), [
    ("para 2026-09-21", [date(2026, 9, 21)]),
    ("para 2026‑09‑21", [date(2026, 9, 21)]),
    ("para 2026–09–21", [date(2026, 9, 21)]),
    ("para 2026−09−21", [date(2026, 9, 21)]),
    ("el 21/09/2026", [date(2026, 9, 21)]),
    ("el 21-09-2026", [date(2026, 9, 21)]),
    ("el 21 de septiembre", [date(2026, 9, 21)]),
    ("el 21 de Septiembre de 2026", [date(2026, 9, 21)]),
    ("EL 21 DE SEPTIEMBRE DEL 2026", [date(2026, 9, 21)]),
    ("el 21 de setiembre", [date(2026, 9, 21)]),
    ("el 5 de enero", [date(2027, 1, 5)]),
    ("hoy", [FIXED_TODAY]),
    ("pasado mañana", [date(2026, 9, 19)]),
    ("mañana", [date(2026, 9, 18)]),
    ("en la mañana", []),
    ("+502 2300-0000", []),
    ("sin fecha", []),
])
def test_extract_dates_formats(text, expected):
    dates, ambiguous = extract_dates(text, FIXED_TODAY)
    assert dates == expected
    assert ambiguous is False


@pytest.mark.parametrize("text", [
    "el 31/02/2026", "el 21/09", "el 09/21/2026", "el sábado", "este fin de semana", "2026-13-01",
])
def test_ambiguous_or_impossible_dates_are_flagged(text):
    _dates, ambiguous = extract_dates(text, FIXED_TODAY)
    assert ambiguous is True


def _marginal(build_context):
    context = build_context({EVALUATED: make_snapshot(EVALUATED, wind_speed_10m_kmh=25.0)})
    evaluate_jump_day(context, EVALUATED.isoformat())
    return context


@pytest.mark.parametrize("message", [
    "Acepto tándem experimentado para el 21 de septiembre",
    "Acepto tándem experimentado para el 21 de septiembre de 2026",
    "Acepto tandem experimentado para 21/09/2026",
    "Acepto tandem experimentado para 21-09-2026",
    "Acepto tandem experimentado para 2026‑09‑21",
    "ACEPTO TÁNDEM EXPERIMENTADO PARA EL 21 DE SEPTIEMBRE",
])
def test_a_different_date_never_confirms_the_evaluated_one(build_context, message):
    context = _marginal(build_context)
    context.observe_user_message(message)
    assert context.confirmed_tandem_date is None
    assert context.jump_assessment is None  # the evaluated date is no longer current


@pytest.mark.parametrize("message", [
    "Acepto tándem experimentado para el sábado",
    "Acepto tándem experimentado para el 21/09",
    "Acepto tándem experimentado para el 31/02/2026",
])
def test_an_ambiguous_date_does_not_confirm(build_context, message):
    context = _marginal(build_context)
    context.observe_user_message(message)
    assert context.confirmed_tandem_date is None


@pytest.mark.parametrize("message", [
    "Acepto tándem experimentado",
    "Sí, acepto el tándem experimentado",
    "Ok, acepto tándem experimentado, no hay problema",
    "Acepto tandem con instructor experimentado para el 20 de septiembre",
    "Confirmo tándem experimentado para 20/09/2026",
    "Acepto tándem experimentado para 2026‑09‑20",
])
def test_matching_or_absent_date_confirms_the_active_marginal_date(build_context, message):
    context = _marginal(build_context)
    context.observe_user_message(message)
    assert context.confirmed_tandem_date == EVALUATED


@pytest.mark.parametrize("message", [
    "No acepto tándem experimentado",
    "Rechazo el tándem experimentado",
    "Prefiero no hacer tándem experimentado",
    "Acepto, pero sin tándem",
])
def test_explicit_rejection_invalidates(build_context, message):
    context = _marginal(build_context)
    context.observe_user_message("Acepto tándem experimentado")
    context.observe_user_message(message)
    assert context.confirmed_tandem_date is None
