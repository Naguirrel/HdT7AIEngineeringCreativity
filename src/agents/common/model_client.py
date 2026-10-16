"""Construye el modelo de OpenAI Agents SDK apuntando a un proveedor compatible (p.ej. Groq)."""

from agents import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from src.config import AppConfig


def build_model(config: AppConfig) -> OpenAIChatCompletionsModel:
    """Groq (y otros proveedores compatibles) exponen la API de Chat Completions, no Responses."""
    client = AsyncOpenAI(api_key=config.llm_api_key, base_url=config.llm_base_url)
    return OpenAIChatCompletionsModel(model=config.llm_model, openai_client=client)
