"""Domain validation of appointment data and tool date normalization (AUD-004, AUD-019)."""

from datetime import date

import pytest

from src.domain.appointment_models import AppointmentData, normalize_contact, normalize_customer_name
from src.domain.dates import normalized_date_or_none, parse_date_argument


@pytest.mark.parametrize(("raw", "expected"), [
    ("Ana Ejemplo", "Ana Ejemplo"),
    ("  José   Pérez ", "José Pérez"),
    ("María de los Ángeles", "María de los Ángeles"),
    ("Jean-Luc O'Neill", "Jean-Luc O'Neill"),
    ("Lu", "Lu"),
    ("Ñandú Q.", "Ñandú Q."),
])
def test_valid_names(raw, expected):
    assert normalize_customer_name(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "   ", "A", "1234", "Ana\x00", "Ana\nLopez", "Ana'); DROP TABLE x;--", "<script>alert(1)</script>",
    "Ana@Lopez", "Ana_Lopez", None, 123, "A" * 201,
])
def test_invalid_names(raw):
    with pytest.raises(ValueError):
        normalize_customer_name(raw)


@pytest.mark.parametrize(("raw", "expected"), [
    ("ana@example.invalid", "ana@example.invalid"),
    ("Ana.Lopez+salto@Example.COM", "ana.lopez+salto@example.com"),
    ("5555-1234", "+50255551234"),
    ("5555 1234", "+50255551234"),
    ("+502 2300-0000", "+50223000000"),
    ("50223000000", "+50223000000"),
    ("+1 (415) 555-2671", "+14155552671"),
    ("+44 20 7946 0958", "+442079460958"),
])
def test_valid_contacts(raw, expected):
    assert normalize_contact(raw) == expected


@pytest.mark.parametrize("raw", [
    "12", "un dato inválido", "ana@", "@example.com", "ana@example", "ana@@example.com",
    "ana..lopez@example.com", "555-123", "+0123456789", "123456789", "ana@exa mple.com",
    "x" * 255, "", "   ", None, "tel\x07", "5555-1234; DROP",
])
def test_invalid_contacts(raw):
    with pytest.raises(ValueError):
        normalize_contact(raw)


def test_appointment_data_stores_normalized_values_and_keeps_strict_types():
    data = AppointmentData(" Ana  Ejemplo ", "5555 1234", date(2026, 9, 20), True, 2)
    assert (data.customer_name, data.contact) == ("Ana Ejemplo", "+50255551234")
    for overrides in ({"is_experienced_tandem": 1}, {"party_size": True}, {"party_size": 0}, {"party_size": "2"}):
        values = dict(customer_name="Ana", contact="ana@example.com", jump_date=date(2026, 9, 20))
        values.update(overrides)
        with pytest.raises(ValueError):
            AppointmentData(**values)


@pytest.mark.parametrize("raw", ["2026-09-20", " 2026-09-20 ", "2026-9-20", "2026‑09‑20", "2026−09−20"])
def test_date_arguments_normalize_once(raw):
    assert parse_date_argument(raw) == date(2026, 9, 20)
    assert normalized_date_or_none(raw) == "2026-09-20"


@pytest.mark.parametrize("raw", ["20/09/2026", "2026-02-30", "2026-09", "", None, 20260920, "2026-09-20T10:00"])
def test_invalid_date_arguments(raw):
    with pytest.raises(ValueError):
        parse_date_argument(raw)
    assert normalized_date_or_none(raw) is None
