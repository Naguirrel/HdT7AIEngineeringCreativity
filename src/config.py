"""Configuracion central compartida por las tres arquitecturas de agentes."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse


DEFAULT_FAQ_PATH = Path(__file__).resolve().parent.parent / "data" / "FAQs_Parachute_SA_Guatemala_2026.txt"

DROP_ZONE_LATITUDE = 14.013722
DROP_ZONE_LONGITUDE = -90.771611

MAX_FORECAST_HORIZON_DAYS = 15

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


class ConfigError(ValueError):
    """La configuracion necesaria no esta disponible o no es valida."""


@dataclass(frozen=True)
class AppConfig:
    llm_api_key: str = field(repr=False)
    llm_base_url: str
    llm_model: str
    faq_path: Path


def load_config(environ: Mapping[str, str] | None = None) -> AppConfig:
    """Construye la configuracion a partir del entorno (compatible con cualquier proveedor tipo OpenAI, p.ej. Groq)."""
    source = os.environ if environ is None else environ
    values = {
        name: source.get(name, "").strip()
        for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ConfigError("Faltan variables de entorno requeridas: " + ", ".join(missing))

    base_url = values["LLM_BASE_URL"].rstrip("/")
    parsed_url = urlparse(base_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ConfigError("LLM_BASE_URL debe ser una URL HTTP(S) completa, normalmente terminada en /v1.")

    configured_path = source.get("FAQ_PATH", "").strip()
    faq_path = Path(configured_path) if configured_path else DEFAULT_FAQ_PATH

    return AppConfig(
        llm_api_key=values["LLM_API_KEY"],
        llm_base_url=base_url,
        llm_model=values["LLM_MODEL"],
        faq_path=faq_path,
    )
