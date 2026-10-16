"""Deterministic grounding of exact entities in user-facing answers.

General policy (no corpus answers are encoded here): every sensitive exact entity in an
answer (phone, e-mail, URL, date, time, number with unit or currency, multi-word proper
name) must appear in a trusted source of the current turn: FAQ entries retrieved now,
business tool outputs, the user's own messages, recorded appointments or the published
weather policy. Otherwise the entity is not shown to the user.
"""

import re
import unicodedata

from src.agents.common.context import ParachuteContext
from src.agents.common.user_message import date_mentions, normalize_text, strip_dates

WEATHER_POLICY_TEXT = (
    "Viento en superficie: ideal < 20 km/h, marginal 20-28 km/h, prohibido > 28 km/h. "
    "Rafagas: prohibido > 35 km/h. Precipitacion: se requiere 0.0 mm; > 0.0 mm prohibido. "
    "Nubes: ideal < 30%, marginal 30-75%, prohibido > 75%. Horizonte de pronostico: 16 dias (hoy + 15)."
)
DOMAIN_ABSTENTION = (
    "Solo puedo ayudarte con Parachute S.A.: sus preguntas frecuentes, el clima para saltar "
    "y las citas. No tengo informacion verificada para responder eso."
)
FAQ_ABSTENTION = "No encontre ese dato en las FAQ oficiales de Parachute S.A."

_EMAIL = re.compile(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}")
_URL = re.compile(r"\b(?:https?://)?(?:www\.)?(?:[a-z0-9\-]+\.)+[a-z]{2,}(?:/[^\s)]*)?")
_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?\s?m\.?|p\.?\s?m\.?)(?![a-z])|\b(\d{1,2}):(\d{2})\b")
_PHONE = re.compile(r"\+?\d[\d\s\-().]{6,}\d")
_MONEY = re.compile(r"(?:\bq|\$|\busd|\bgtq)\s?\d[\d.,]*|\d[\d.,]*\s?(?:quetzales|dolares|usd|gtq)\b")
_UNIT_NUMBER = re.compile(
    r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(?:kg|kilos?|kilogramos?|lbs?|libras?|min(?:utos)?|horas?|anos|"
    r"%|por ciento|km/h|mm|c\b|grados|personas|participantes|metros|m\b|pies)"
)
_CAPITALIZED = r"[A-ZÁÉÍÓÚÑÜ][\wÁÉÍÓÚÑÜáéíóúñü'\-]*"
_GAP = r"[   ]+"  # names never span table cells or line breaks
_PROPER_SPAN = re.compile(
    rf"{_CAPITALIZED}(?:{_GAP}(?:(?:de|del|la|las|los|y|e){_GAP})?{_CAPITALIZED})+"
)
# Capitalized words that are ordinary vocabulary in this domain, not named entities.
_COMMON_WORDS = set("""
a al el la los las lo un una y e o de del en con sin por para segun si no tu su sus mi hola gracias
claro perfecto listo nota importante recuerda ademas tambien requisito requisitos detalle detalles
respuesta resumen fecha lugar hora horario edad minima maxima peso limite ropa calzado contacto
telefono correo sitio web whatsapp faq faqs cita citas reserva reservas clima evento salto saltos
tandem marginal ideal prohibido prohibited dia viento rafagas precipitacion nubes temperatura estado
decision acompanamiento documento identificacion oficial menores mayores padres tutores carta
responsabilidad camaras celulares paquete paquetes participantes participante instructor experimentado
parachute guatemala lunes martes miercoles jueves viernes sabado domingo enero febrero marzo abril
mayo junio julio agosto septiembre setiembre octubre noviembre diciembre am pm s.a sa lo siento
""".split())


def _plain(text: str) -> str:
    """Drop Markdown emphasis; table cell borders become line breaks."""
    return re.sub(r"[*_`#>]", "", text.replace("|", "\n"))


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", normalize_text(text)))


def _numbers(text: str) -> set[float]:
    values = set()
    for raw in re.findall(r"\d+(?:[.,]\d+)?", strip_dates(text)):
        try:
            values.add(float(raw.replace(",", ".")))
        except ValueError:
            continue
    return values


def _times(text: str) -> set[tuple[int, int]]:
    found = set()
    for match in _TIME.finditer(normalize_text(text)):
        if match.group(4):
            hour, minute = int(match.group(4)), int(match.group(5))
        else:
            hour, minute = int(match.group(1)), int(match.group(2) or 0)
            if match.group(3).startswith("p") and hour < 12:
                hour += 12
            if match.group(3).startswith("a") and hour == 12:
                hour = 0
        found.add((hour, minute))
    return found


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def turn_sources(context: ParachuteContext) -> str:
    parts = [WEATHER_POLICY_TEXT]
    parts.extend(f"{entry['question']}\n{entry['answer']}" for entry in context.turn_faq_entries)
    parts.extend(context.turn_tool_outputs)
    parts.extend(context.user_messages)
    for record in context.appointments:
        data = record.data
        parts.append(f"{data.customer_name} {data.contact} {data.jump_date.isoformat()} {data.party_size} personas")
    return "\n".join(parts)


def ungrounded_entities(answer: str, sources: str) -> list[str]:
    """Exact entities in `answer` that no trusted source contains."""
    text = _plain(answer)
    lowered = normalize_text(text)
    source_lowered = normalize_text(sources)
    source_digits = [_digits(match) for match in _PHONE.findall(strip_dates(sources))]
    source_tokens = _tokens(sources)
    source_numbers = _numbers(sources)
    violations: list[str] = []

    for email in _EMAIL.findall(lowered):
        if email not in source_lowered:
            violations.append(email)
    without_emails = _EMAIL.sub(" ", lowered)
    for url in _URL.findall(without_emails):
        core = re.sub(r"^(?:https?://)?(?:www\.)?", "", url).rstrip("/.")
        if core not in source_lowered:
            violations.append(url)

    answer_dates = date_mentions(text)
    source_dates = date_mentions(sources)
    for year, month, day in answer_dates:
        if not any(
            month == s_month and day == s_day and (year is None or s_year is None or year == s_year)
            for s_year, s_month, s_day in source_dates
        ):
            violations.append(f"{day}/{month}" + (f"/{year}" if year else ""))

    source_times = _times(sources)
    for hour, minute in _times(text):
        if (hour, minute) not in source_times:
            violations.append(f"{hour:02d}:{minute:02d}")

    without_dates = _TIME.sub(" ", strip_dates(text))
    for phone in _PHONE.findall(without_dates):
        digits = _digits(phone)
        if len(digits) >= 7 and not any(digits in known or known.endswith(digits) for known in source_digits):
            violations.append(phone.strip())

    for amount in _MONEY.findall(without_dates):
        if not (_numbers(amount) <= source_numbers and re.search(r"(?:\bq\b|quetzal|\$|usd|gtq)", source_lowered)):
            violations.append(amount.strip())
    for value in _UNIT_NUMBER.findall(without_dates):
        if float(value.replace(",", ".")) not in source_numbers:
            violations.append(value)

    for span in _PROPER_SPAN.findall(text):
        words = [
            word for word in re.findall(r"[a-z0-9]+", normalize_text(span))
            if word not in _COMMON_WORDS and len(word) > 2
        ]
        if any(word not in source_tokens for word in words):
            violations.append(span)
    return violations


def _faq_fallback(context: ParachuteContext) -> str:
    seen: list[str] = []
    for entry in context.turn_faq_entries:
        if entry["answer"] not in seen:
            seen.append(entry["answer"])
    if not seen:
        return FAQ_ABSTENTION
    return "Segun las FAQ oficiales de Parachute S.A.:\n" + "\n\n".join(seen)


# A sentence ends at . ! ? followed by whitespace (not inside "28.1") or at a line break.
_SENTENCE = re.compile(r".+?(?:[.!?](?=\s|$)\s*|\n|$)", re.S)


def ground_answer(context: ParachuteContext, answer: str) -> str:
    """Return the answer unchanged when grounded; otherwise a safe, source-backed reply."""
    sources = turn_sources(context)
    if not ungrounded_entities(answer, sources):
        return answer
    faq_turn = any(event_tool == "search_faq" for event_tool in context.turn_tools)
    if faq_turn:
        return _faq_fallback(context)
    if not context.turn_tools:
        return DOMAIN_ABSTENTION
    kept = [part for part in _SENTENCE.findall(answer) if not ungrounded_entities(part, sources)]
    remaining = unicodedata.normalize("NFC", "".join(kept)).strip()
    return remaining or DOMAIN_ABSTENTION
