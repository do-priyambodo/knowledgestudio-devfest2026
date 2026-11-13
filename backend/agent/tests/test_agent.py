"""Contract tests for all 3 DevFest KL 2026 ADK dropdown agents (no live LLM calls)."""

from __future__ import annotations

import os

import pytest
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.mcp_tool import McpToolset

from agent_1_without_kc.agent import app as app_1
from agent_1_without_kc.agent import root_agent as agent_1
from agent_2_with_kc.agent import app as app_2
from agent_2_with_kc.agent import root_agent as agent_2
from app.agent import MAX_OUTPUT_TOKENS, AgentTurn, configure_adk_environment, root_agent
from app.agent import app as arena_app
from app.builders import build_with_kc_agent, build_without_kc_agent


def test_all_three_dropdown_packages_export_valid_adk_apps() -> None:
    """adk web requires each package to export both root_agent and app = App(...)."""
    for pkg_agent, pkg_app, expected_app_name in [
        (agent_1, app_1, "agent_1_without_kc"),
        (agent_2, app_2, "agent_2_with_kc"),
        (root_agent, arena_app, "app"),
    ]:
        assert isinstance(pkg_agent, Agent)
        assert isinstance(pkg_app, App)
        assert pkg_app.name == expected_app_name
        assert pkg_agent.generate_content_config is not None
        assert (pkg_agent.generate_content_config.max_output_tokens or 0) >= MAX_OUTPUT_TOKENS


def test_agent_1_has_no_knowledge_catalog_mcp_while_agent_2_does() -> None:
    """Proves the comparison is structurally honest: same model, only Knowledge Studio MCP differs."""
    assert agent_1.model == agent_2.model
    assert not any(isinstance(t, McpToolset) for t in agent_1.tools)
    assert any(isinstance(t, McpToolset) for t in agent_2.tools)


def test_arena_orchestrator_wraps_both_specialists_via_agent_tool() -> None:
    """Arena app delegates to isolated specialist instances via AgentTool."""
    wrapped_names = [t.agent.name for t in root_agent.tools if isinstance(t, AgentTool)]
    assert "without_knowledgestudio_specialist" in wrapped_names
    assert "with_knowledgestudio_specialist" in wrapped_names


def test_agent_turn_assert_valid_enforces_turn_invariants() -> None:
    """AgentTurn rejects truncated, empty, or tool-skipping turns."""
    valid_turn = AgentTurn(
        text="Q3 2026 Governed Net Revenue is RM 1,280,000.00.",
        finish_reason="STOP",
        tool_calls={"lookup_context": 1, "run_readonly_bigquery_sql": 1},
    )
    valid_turn.assert_valid(required_tools=("lookup_context",))

    with pytest.raises(RuntimeError, match="MAX_TOKENS"):
        AgentTurn(text="partial...", finish_reason="MAX_TOKENS", tool_calls={"lookup_context": 1}).assert_valid()

    with pytest.raises(RuntimeError, match="empty"):
        AgentTurn(text="   ", finish_reason="STOP", tool_calls={}).assert_valid()

    with pytest.raises(RuntimeError, match="lookup_context"):
        AgentTurn(text="Guessed RM 1.84M", finish_reason="STOP", tool_calls={}).assert_valid(
            required_tools=("lookup_context",)
        )


def test_builder_factories_return_distinct_unbound_agents() -> None:
    """Factory builders produce fresh Agent objects with parent_agent == None."""
    fresh_1 = build_without_kc_agent("custom_without_kc")
    fresh_2 = build_with_kc_agent("custom_with_kc")
    assert fresh_1 is not agent_1
    assert fresh_2 is not agent_2
    assert fresh_1.parent_agent is None
    assert fresh_2.parent_agent is None


def test_configure_adk_environment_forces_global_for_gemini_4(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini 4 (Hydrogen / Argon) on Vertex AI requires GOOGLE_CLOUD_LOCATION='global'."""
    assert agent_1.model == "gemini-4-hydrogen"
    assert agent_2.model == "gemini-4-hydrogen"
    assert root_agent.model == "gemini-4-hydrogen"
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    configure_adk_environment()
    assert os.environ["GOOGLE_CLOUD_LOCATION"] == "global"
    assert os.environ["GOOGLE_GENAI_USE_VERTEXAI"] == "1"


def test_both_specialists_share_identical_bigquery_tools_differing_only_by_kc_mcp() -> None:
    """Proves pure Knowledge Studio experiment: identical BigQuery tools, only McpToolset differs."""
    bq_tools_1 = [getattr(t, "__name__", "") for t in agent_1.tools if not isinstance(t, McpToolset)]
    bq_tools_2 = [getattr(t, "__name__", "") for t in agent_2.tools if not isinstance(t, McpToolset)]
    assert bq_tools_1 == ["inspect_bigquery_schema", "run_readonly_bigquery_sql"]
    assert bq_tools_2 == ["inspect_bigquery_schema", "run_readonly_bigquery_sql"]
    assert len([t for t in agent_2.tools if isinstance(t, McpToolset)]) == 1


def test_thinking_config_enabled_at_low_level_for_stage_speed() -> None:
    """All agents run LOW thinking level with include_thoughts=False to skip thought-summarizer latency."""
    for target in (agent_1, agent_2, root_agent):
        assert target.generate_content_config is not None
        tc = target.generate_content_config.thinking_config
        assert tc is not None
        assert tc.include_thoughts is False
