"""Unit tests for the agent service runtime switch (in-process vs Vertex AI Agent Runtime)."""

import asyncio

import pytest
from app.agent import AgentTurn

from api.features.agent.service import (
    AgentTimeoutError,
    AgentTurnError,
    run_agent,
    validate_agent_runtime_resource,
)
from api.platform.config import settings


def test_validate_agent_runtime_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_RUNTIME_RESOURCE", raising=False)
    assert validate_agent_runtime_resource(None) is None

    valid_res = "projects/my-gcp-project/locations/us-central1/reasoningEngines/engine-123"
    monkeypatch.setenv("AGENT_RUNTIME_RESOURCE", valid_res)
    assert validate_agent_runtime_resource() == valid_res

    monkeypatch.setenv("AGENT_RUNTIME_RESOURCE", "bogus-resource-string")
    with pytest.raises(ValueError, match="Malformed AGENT_RUNTIME_RESOURCE"):
        validate_agent_runtime_resource()


@pytest.mark.asyncio
async def test_run_agent_in_process_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_RUNTIME_RESOURCE", raising=False)

    async def fake_local_collector(_agent: object, prompt: str, user_id: str) -> AgentTurn:
        turn = AgentTurn()
        turn.text = f"local:{user_id}:{prompt}"
        turn.finish_reason = "STOP"
        turn.tool_calls = {"search": 1}
        return turn

    res = await run_agent("hello world", "user-123", local_collector=fake_local_collector)
    assert res.text == "local:user-123:hello world"
    assert res.finish_reason == "STOP"
    assert res.tool_calls == {"search": 1}


@pytest.mark.asyncio
async def test_run_agent_remote_runtime_success(monkeypatch: pytest.MonkeyPatch) -> None:
    valid_res = "projects/my-gcp-project/locations/us-central1/reasoningEngines/engine-123"
    monkeypatch.setenv("AGENT_RUNTIME_RESOURCE", valid_res)
    captured: list[tuple[str, str, str, str]] = []

    async def fake_remote_caller(
        resource: str,
        user_id: str,
        session_id: str,
        message: str,
    ) -> AgentTurn:
        captured.append((resource, user_id, session_id, message))
        turn = AgentTurn()
        turn.text = "remote response"
        turn.finish_reason = "STOP"
        turn.tool_calls = {"lookup": 2}
        return turn

    res = await run_agent("test prompt", "user-456", remote_caller=fake_remote_caller)
    assert res.text == "remote response"
    assert res.tool_calls == {"lookup": 2}
    assert captured == [(valid_res, "user-456", "user-456", "test prompt")]


@pytest.mark.asyncio
async def test_run_agent_remote_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    valid_res = "projects/my-gcp-project/locations/us-central1/reasoningEngines/engine-123"
    monkeypatch.setenv("AGENT_RUNTIME_RESOURCE", valid_res)
    monkeypatch.setattr(settings, "AGENT_TIMEOUT_S", 0.05)

    async def slow_remote_caller(
        _resource: str,
        _user_id: str,
        _session_id: str,
        _message: str,
    ) -> AgentTurn:
        await asyncio.sleep(0.5)
        turn = AgentTurn()
        turn.text = "late"
        turn.finish_reason = "STOP"
        return turn

    with pytest.raises(AgentTimeoutError):
        await run_agent("test prompt", "user-123", remote_caller=slow_remote_caller)


@pytest.mark.asyncio
async def test_run_agent_remote_empty_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    valid_res = "projects/my-gcp-project/locations/us-central1/reasoningEngines/engine-123"
    monkeypatch.setenv("AGENT_RUNTIME_RESOURCE", valid_res)

    async def empty_remote_caller(
        _resource: str,
        _user_id: str,
        _session_id: str,
        _message: str,
    ) -> AgentTurn:
        turn = AgentTurn()
        turn.text = "   "
        turn.finish_reason = "STOP"
        return turn

    with pytest.raises(AgentTurnError):
        await run_agent("test prompt", "user-123", remote_caller=empty_remote_caller)
