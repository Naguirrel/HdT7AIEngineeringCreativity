"""Date source for the drop zone, replaceable by a fixed clock in tests."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


GUATEMALA_TIMEZONE_NAME = "America/Guatemala"
GUATEMALA_TIMEZONE = ZoneInfo(GUATEMALA_TIMEZONE_NAME)


def current_guatemala_date(now: datetime | None = None) -> date:
    instant = datetime.now(timezone.utc) if now is None else now
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("El reloj debe proporcionar una fecha y hora con zona horaria.")
    return instant.astimezone(GUATEMALA_TIMEZONE).date()
