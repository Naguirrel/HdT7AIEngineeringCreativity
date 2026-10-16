"""Verifica que las tres arquitecturas esten realmente diferenciadas y compartan
el mismo nucleo de dominio/servicios, sin necesidad de llamar a un LLM real.
"""

import pytest

from agents import Agent

from src.agents.centralized.main import build_supervisor
from src.agents.common.booking_completion import booking_result_or_continue
from src.agents.common.model_client import build_model
from src.agents.common.specialist_agents import build_faq_agent, build_scheduling_agent
from src.agents.decentralized.main import build_decentralized_agents, build_entry_agent
from src.agents.hierarchical.main import build_root_manager
from src.config import load_config


@pytest.fixture(autouse=True)
def llm_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")


def test_centralized_supervisor_exposes_three_specialists_as_tools():
    supervisor, context = build_supervisor()
    tool_names = {tool.name for tool in supervisor.tools}
    assert tool_names == {"faq_specialist", "weather_specialist", "scheduling_specialist"}
    assert context.services.faq_service.entries
    assert supervisor.tool_use_behavior is booking_result_or_continue


def test_all_entry_agents_share_the_same_critical_rules():
    """Behavior is covered by test_architecture_flows; here we check the single shared source."""
    from src.agents.common.policies import BOOKING_RULES, ENTRY_AGENT_RULES, TRUTHFUL_OUTPUT_RULES

    supervisor, _ = build_supervisor()
    root_manager, _ = build_root_manager()
    entry_agent, _ = build_entry_agent()
    for agent in (supervisor, root_manager, entry_agent):
        assert ENTRY_AGENT_RULES in agent.instructions
    booking_manager = next(tool for tool in root_manager.tools if tool.name == "booking_manager")
    assert booking_manager is not None
    _faq, weather, scheduling = build_decentralized_agents(build_model(load_config()))
    for agent in (weather, scheduling):
        assert BOOKING_RULES in agent.instructions and TRUTHFUL_OUTPUT_RULES in agent.instructions


def test_faq_specialist_grounding_contract():
    faq_agent = build_faq_agent(build_model(load_config()))
    instructions = " ".join(faq_agent.instructions.casefold().split())
    assert "usa siempre la herramienta search_faq" in instructions
    assert "responde exclusivamente con los datos devueltos por search_faq" in instructions
    assert "numeros telefonicos, correos, fechas, direcciones" in instructions
    assert "no completes datos con ejemplos comunes ni conocimiento general" in instructions
    assert "si el contexto no contiene el dato solicitado" in instructions
    assert "identifica el grupo del usuario y prioriza sus requisitos" in instructions
    assert "no presentes una regla general y su excepcion como obligaciones simultaneas" in instructions
    assert faq_agent.tool_use_behavior == "stop_on_first_tool"
    assert [tool.name for tool in faq_agent.tools] == ["search_faq"]


def test_scheduling_specialist_requires_complete_workflow():
    agent = build_scheduling_agent(build_model(load_config()))
    instructions = " ".join(agent.instructions.casefold().split())
    assert "check_jump_day, despues check_appointment_availability y finalmente create_appointment" in instructions
    assert "no llames create_appointment si la disponibilidad no fue comprobada y aprobada" in instructions
    assert "si la herramienta confirma la cita, informa el exito y la fecha" in instructions
    assert agent.tool_use_behavior is booking_result_or_continue


def test_hierarchical_root_manager_has_two_levels():
    root_manager, _context = build_root_manager()
    root_tool_names = {tool.name for tool in root_manager.tools}
    assert root_tool_names == {"knowledge_manager", "booking_manager"}
    assert "faq_specialist" not in root_tool_names
    assert root_manager.tool_use_behavior is booking_result_or_continue
    assert "weather_specialist" not in root_tool_names


def test_decentralized_agents_are_wired_with_handoffs():
    config = load_config()
    from src.agents.common.model_client import build_model

    model = build_model(config)
    faq_agent, weather_agent, scheduling_agent = build_decentralized_agents(model)

    faq_handoff_targets = {h.agent_name for h in faq_agent.handoffs}
    weather_handoff_targets = {h.agent_name for h in weather_agent.handoffs}
    scheduling_handoff_targets = {h.agent_name for h in scheduling_agent.handoffs}

    assert faq_handoff_targets == {"Weather Agent"}
    assert weather_handoff_targets == {"FAQ Agent", "Scheduling Agent"}
    assert scheduling_handoff_targets == {"FAQ Agent"}
    assert scheduling_agent.tool_use_behavior is booking_result_or_continue


def test_decentralized_has_no_permanent_global_supervisor():
    config = load_config()
    from src.agents.common.model_client import build_model

    model = build_model(config)
    faq_agent, weather_agent, scheduling_agent = build_decentralized_agents(model)

    for agent in (faq_agent, weather_agent, scheduling_agent):
        assert isinstance(agent, Agent)
        tool_names = {tool.name for tool in agent.tools}
        assert tool_names.isdisjoint({"faq_specialist", "weather_specialist", "scheduling_specialist"})
