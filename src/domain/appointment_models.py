"""Modelos de dominio para la cita de salto."""

from dataclasses import dataclass
from datetime import date
import re

from .weather_models import JumpAssessment

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_NAME = re.compile(r"[^\W\d_]+(?:[ '\-.]{1,2}[^\W\d_]+)*\.?")
_EMAIL = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)*\.[A-Za-z]{2,}"
)
_GUATEMALA_PHONE = re.compile(r"(?:\+?502)?(\d{8})")
_E164 = re.compile(r"\+[1-9]\d{7,14}")

CONTACT_RULE = (
    "El contacto debe ser un correo valido o un telefono: 8 digitos de Guatemala "
    "(opcionalmente con +502) o formato internacional +<codigo><numero>."
)


def normalize_customer_name(value: object) -> str:
    """Collapse whitespace and reject anything that is not a plausible person name."""
    if not isinstance(value, str):
        raise ValueError("El nombre del cliente debe ser un texto no vacio.")
    if _CONTROL.search(value):
        raise ValueError("El nombre del cliente contiene caracteres no permitidos.")
    name = " ".join(value.split())
    if not name:
        raise ValueError("El nombre del cliente debe ser un texto no vacio.")
    if len(name) > 200:
        raise ValueError("El nombre del cliente excede 200 caracteres.")
    if not _NAME.fullmatch(name):
        raise ValueError("El nombre solo puede contener letras, espacios, guiones, apostrofes y puntos.")
    if sum(char.isalpha() for char in name) < 2:
        raise ValueError("El nombre del cliente debe tener al menos dos letras.")
    return name


def normalize_contact(value: object) -> str:
    """Return a canonical e-mail (lowercase) or phone (+502XXXXXXXX or E.164)."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("El contacto debe ser un texto no vacio.")
    if _CONTROL.search(value):
        raise ValueError("El contacto contiene caracteres no permitidos.")
    contact = value.strip()
    if len(contact) > 254:
        raise ValueError("El contacto excede 254 caracteres.")
    if "@" in contact:
        if _EMAIL.fullmatch(contact) and ".." not in contact:
            return contact.lower()
        raise ValueError(CONTACT_RULE)
    compact = re.sub(r"[\s\-.()]", "", contact)
    local = _GUATEMALA_PHONE.fullmatch(compact)
    if local:
        return f"+502{local.group(1)}"
    if _E164.fullmatch(compact):
        return compact
    raise ValueError(CONTACT_RULE)


@dataclass(frozen=True)
class AppointmentData:
    customer_name: str
    contact: str
    jump_date: date
    is_experienced_tandem: bool = False
    party_size: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "customer_name", normalize_customer_name(self.customer_name))
        object.__setattr__(self, "contact", normalize_contact(self.contact))
        if type(self.jump_date) is not date:
            raise ValueError("La fecha de la cita debe ser una fecha valida.")
        if type(self.is_experienced_tandem) is not bool:
            raise ValueError("La confirmacion de tandem debe ser un valor booleano.")
        if type(self.party_size) is not int or self.party_size < 1:
            raise ValueError("El numero de participantes debe ser un entero mayor o igual a 1.")


@dataclass(frozen=True)
class AppointmentRecord:
    id: str
    data: AppointmentData
    assessment: JumpAssessment
