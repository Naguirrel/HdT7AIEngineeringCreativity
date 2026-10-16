"""Deterministic extraction of booking data from the user's own words.

The supervisor delegates through as_tool(), so specialists only receive the text the
supervisor chooses to forward. Keeping the user's data in the context avoids losing
name, contact, party size or date between turns and nested agents.
"""

from dataclasses import dataclass
from datetime import date, timedelta
import re
import unicodedata

_DASHES = re.compile(r"[‐-―−]")
_ISO_DATE = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\w+])(\+\d[\d\s\-]{6,16}\d|\d{4}[\s\-]?\d{4})(?![\w])")
_NAME_WORD = r"[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü'\-]+"
_FULL_NAME = rf"{_NAME_WORD}(?:\s+{_NAME_WORD}){{1,3}}"
_NAME_PATTERNS = (
    re.compile(rf"\b(?:a nombre de|mi nombre es|me llamo|nombre:)\s+({_NAME_WORD}(?:\s+{_NAME_WORD}){{0,3}})"),
    re.compile(rf"\bpara\s+({_FULL_NAME})"),
    re.compile(rf":\s*({_FULL_NAME})\s*,"),
)
_NUMBER_WORDS = {
    "un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
}
_PARTY_SIZE = re.compile(
    r"\b(?:somos|seremos|para)?\s*(-?\d{1,3}|" + "|".join(_NUMBER_WORDS) + r")\s+(?:personas?|participantes?|saltadores?)\b"
)
_BOOKING_INTENT = re.compile(r"\b(?:reserv\w*|agend\w*|cita|apart\w*|confirma la cita)\b")


def normalize_text(text: str) -> str:
    """Casefold, strip accents and unify Unicode dashes and spaces."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", _DASHES.sub("-", without_marks))


_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}
_DMY_DATE = re.compile(r"(?<![\d/\-])(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})(?![\d/\-])")
_PARTIAL_NUMERIC_DATE = re.compile(r"(?<![\d/\-])\d{1,2}/\d{1,2}(?![\d/\-])")
_TEXT_DATE = re.compile(
    r"\b(\d{1,2})\s+(?:de\s+)?(" + "|".join(_MONTHS) + r")\b(?:\s+(?:de|del)?\s*(\d{4})\b)?"
)
_WEEKDAYS = re.compile(r"\b(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo|fin de semana)\b")


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def extract_dates(text: str, today: date | None = None) -> tuple[list[date], bool]:
    """Parse the dates a user wrote and flag anything that cannot be resolved safely.

    Supported: YYYY-MM-DD (any Unicode dash), DD/MM/YYYY, DD-MM-YYYY, "21 de septiembre"
    and "21 de septiembre de 2026"; "hoy", "mañana" and "pasado mañana" when `today` is known.
    Impossible dates, day/month without year in numeric form and weekdays are ambiguous.
    """
    normalized = normalize_text(text)
    found: list[date] = []
    ambiguous = False

    def consume(pattern: re.Pattern, source: str, build) -> str:
        nonlocal ambiguous
        for match in pattern.finditer(source):
            value = build(match)
            if value is None:
                ambiguous = True
            else:
                found.append(value)
        return pattern.sub(" ", source)

    remaining = consume(
        _ISO_DATE, normalized, lambda m: _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    )
    remaining = consume(
        _DMY_DATE, remaining, lambda m: _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    )

    def textual(match: re.Match) -> date | None:
        day, month = int(match.group(1)), _MONTHS[match.group(2)]
        if match.group(3):
            return _safe_date(int(match.group(3)), month, day)
        if today is None:
            return None
        candidate = _safe_date(today.year, month, day)
        if candidate is not None and candidate < today:
            candidate = _safe_date(today.year + 1, month, day)
        return candidate

    remaining = consume(_TEXT_DATE, remaining, textual)
    if _PARTIAL_NUMERIC_DATE.search(remaining) or _WEEKDAYS.search(remaining):
        ambiguous = True

    if today is not None:
        if re.search(r"\bpasado manana\b", remaining):
            found.append(today + timedelta(days=2))
            remaining = re.sub(r"\bpasado manana\b", " ", remaining)
        if re.search(r"(?<!\bla )(?<!\bpor la )\bmanana\b", remaining):
            found.append(today + timedelta(days=1))
        if re.search(r"\bhoy\b", remaining):
            found.append(today)
    return found, ambiguous


def date_mentions(text: str) -> list[tuple[int | None, int, int]]:
    """(year or None, month, day) for every explicit date, without guessing missing years."""
    normalized = normalize_text(text)
    mentions: list[tuple[int | None, int, int]] = []
    for match in _ISO_DATE.finditer(normalized):
        mentions.append((int(match.group(1)), int(match.group(2)), int(match.group(3))))
    remaining = _ISO_DATE.sub(" ", normalized)
    for match in _DMY_DATE.finditer(remaining):
        mentions.append((int(match.group(3)), int(match.group(2)), int(match.group(1))))
    remaining = _DMY_DATE.sub(" ", remaining)
    for match in _TEXT_DATE.finditer(remaining):
        year = int(match.group(3)) if match.group(3) else None
        mentions.append((year, _MONTHS[match.group(2)], int(match.group(1))))
    return mentions


def strip_dates(text: str) -> str:
    """Normalized text with explicit dates removed (so their digits are not read as numbers)."""
    normalized = normalize_text(text)
    for pattern in (_ISO_DATE, _DMY_DATE, _TEXT_DATE):
        normalized = pattern.sub(" ", normalized)
    return normalized


@dataclass(frozen=True)
class MessageDetails:
    dates: tuple[date, ...] = ()
    ambiguous_date: bool = False
    customer_name: str | None = None
    contact: str | None = None
    party_size: int | None = None
    booking_intent: bool = False


def extract_booking_details(message: str, today: date | None = None) -> MessageDetails:
    dates, ambiguous = extract_dates(message, today)
    normalized = normalize_text(message)

    contact = None
    email = _EMAIL.search(message)
    if email:
        contact = email.group(0)
    else:
        phone = _PHONE.search(_DASHES.sub("-", message))
        if phone:
            contact = phone.group(1).strip()

    booking_words = bool(_BOOKING_INTENT.search(normalized))
    name = None
    # "para Nombre Apellido" only names a customer when the message is about a booking.
    for pattern in _NAME_PATTERNS if booking_words else _NAME_PATTERNS[:1]:
        match = pattern.search(message)
        if match:
            name = match.group(1).strip()
            break

    party_size = None
    party = _PARTY_SIZE.search(normalized)
    if party:
        token = party.group(1)
        party_size = _NUMBER_WORDS.get(token, None) if not token.lstrip("-").isdigit() else int(token)

    intent = booking_words and "?" not in message
    return MessageDetails(
        dates=tuple(dates), ambiguous_date=ambiguous, customer_name=name,
        contact=contact, party_size=party_size, booking_intent=intent,
    )
