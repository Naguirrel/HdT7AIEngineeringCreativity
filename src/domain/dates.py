"""Single normalization point for date arguments received by the agent tools."""

from datetime import date
import re

_DASHES = re.compile(r"[‐-―−]")
_ISO_LIKE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


def parse_date_argument(value: object) -> date:
    """Accept YYYY-MM-DD with surrounding spaces, Unicode dashes or unpadded parts.

    The returned date is what state, tools and traces must use (via `isoformat()`).
    """
    if not isinstance(value, str):
        raise ValueError("La fecha debe ser un texto en formato YYYY-MM-DD.")
    match = _ISO_LIKE.fullmatch(_DASHES.sub("-", value.strip()))
    if not match:
        raise ValueError("La fecha debe tener formato YYYY-MM-DD.")
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError as error:
        raise ValueError("La fecha indicada no existe en el calendario.") from error


def normalized_date_or_none(value: object) -> str | None:
    """ISO string for traces; None when the argument is not a valid date."""
    try:
        return parse_date_argument(value).isoformat()
    except ValueError:
        return None
