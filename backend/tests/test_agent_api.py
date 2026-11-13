"""Unit tests for the in-process agent endpoint (2-folder layout only).

init-project.sh deletes this file together with src/api/features/agent in the
3-folder layout, where the agent is its own service. No model is called: the
authorized cases replace `collect_agent_turn` in the service module.
"""

import asyncio

import pytest
from app.agent import AgentTurn
from httpx import AsyncClient
from pydantic import SecretStr

from api.features.agent import service
from api.platform.config import settings

KEY = "k" * 40
URL = "/api/v1/agent/run"
AUTH = {"X-API-Key": KEY}


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AGENT_API_KEY", SecretStr(KEY))


def fake_turn(
    monkeypatch: pytest.MonkeyPatch, turn: AgentTurn | None = None, error: Exception | None = None
) -> list[tuple[str, str]]:
    """Replace the model call; returns the (prompt, user_id) pairs the fake received."""
    calls: list[tuple[str, str]] = []

    async def collect(agent: object, prompt: str, user_id: str = "system") -> AgentTurn:
        calls.append((prompt, user_id))
        if error is not None:
            raise error
        assert turn is not None
        return turn

    monkeypatch.setattr(service, "collect_agent_turn", collect)
    return calls


async def test_agent_endpoint_is_disabled_without_api_key(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AGENT_API_KEY", None)
    response = await client.post(URL, json={"prompt": "audit checkout-api"})
    assert response.status_code == 503


@pytest.mark.usefixtures("api_key")
async def test_agent_endpoint_rejects_wrong_api_key(client: AsyncClient) -> None:
    response = await client.post(URL, json={"prompt": "audit checkout-api"}, headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


@pytest.mark.usefixtures("api_key")
async def test_agent_endpoint_returns_a_valid_turn(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_turn(monkeypatch, AgentTurn(text="all green", finish_reason="STOP", tool_calls={"calc": 1}))
    response = await client.post(
        URL, json={"prompt": "  audit checkout-api  ", "user_id": "ops@example.com"}, headers=AUTH
    )
    assert response.status_code == 200
    assert response.json() == {"text": "all green", "finish_reason": "STOP", "tool_calls": {"calc": 1}}
    # user_id is the ADK session identity, so it must reach the agent unchanged.
    assert calls == [("audit checkout-api", "ops@example.com")]


@pytest.mark.usefixtures("api_key")
async def test_agent_endpoint_rejects_a_truncated_turn(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_turn(monkeypatch, AgentTurn(text="half an ans", finish_reason="MAX_TOKENS"))
    response = await client.post(URL, json={"prompt": "audit checkout-api"}, headers=AUTH)
    assert response.status_code == 502


@pytest.mark.usefixtures("api_key")
async def test_agent_endpoint_times_out(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow(agent: object, prompt: str, user_id: str = "system") -> AgentTurn:
        await asyncio.sleep(5)
        return AgentTurn(text="too late", finish_reason="STOP")

    monkeypatch.setattr(service, "collect_agent_turn", slow)
    monkeypatch.setattr(settings, "AGENT_TIMEOUT_S", 0.05)
    response = await client.post(URL, json={"prompt": "audit checkout-api"}, headers=AUTH)
    assert response.status_code == 504


@pytest.mark.usefixtures("api_key")
@pytest.mark.parametrize("error", [ValueError("Project or API key must be set"), RuntimeError("boom internal")])
async def test_agent_endpoint_hides_internal_errors(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    fake_turn(monkeypatch, error=error)
    response = await client.post(URL, json={"prompt": "audit checkout-api"}, headers=AUTH)
    assert response.status_code == 500
    assert response.json() == {"detail": "Agent run failed."}


@pytest.mark.usefixtures("api_key")
async def test_agent_endpoint_rejects_an_empty_prompt(client: AsyncClient) -> None:
    response = await client.post(URL, json={"prompt": ""}, headers=AUTH)
    assert response.status_code == 422


@pytest.mark.usefixtures("api_key")
async def test_agent_endpoint_rejects_a_blank_prompt(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = fake_turn(monkeypatch, AgentTurn(text="unused", finish_reason="STOP"))
    response = await client.post(URL, json={"prompt": " \n\t "}, headers=AUTH)
    assert response.status_code == 422
    assert response.json() == {"detail": "prompt is blank"}
    assert prompts == []


@pytest.mark.usefixtures("api_key")
async def test_agent_endpoint_rejects_a_bad_user_id(client: AsyncClient) -> None:
    response = await client.post(URL, json={"prompt": "audit checkout-api", "user_id": "bad id!"}, headers=AUTH)
    assert response.status_code == 422


@pytest.mark.usefixtures("api_key")
async def test_agent_compare_endpoint_returns_side_by_side_turns(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_compare(prompt: str, user_id: str) -> tuple[AgentTurn, AgentTurn]:
        assert prompt == "What is Q3 Net Revenue?"
        assert user_id == "analyst@example.com"
        return (
            AgentTurn(
                text="RM 1,842,500 (guessed)",
                finish_reason="STOP",
                tool_calls={"run_readonly_bigquery_sql": 1},
                latency_ms=420.0,
            ),
            AgentTurn(
                text="RM 1,280,000 (governed)",
                finish_reason="STOP",
                tool_calls={"lookup_context": 1, "run_readonly_bigquery_sql": 1},
                latency_ms=680.0,
            ),
        )

    monkeypatch.setattr(service, "compare_without_vs_with_kc", fake_compare)
    response = await client.post(
        "/api/v1/agent/compare",
        json={"prompt": "  What is Q3 Net Revenue?  ", "user_id": "analyst@example.com"},
        headers=AUTH,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["without_knowledgestudio"]["agent_name"] == "agent_1_without_kc"
    assert body["with_knowledgestudio"]["agent_name"] == "agent_2_with_kc"
    assert body["with_knowledgestudio"]["tool_calls"]["lookup_context"] == 1


def test_extract_executive_fields_parses_myr_bullets_and_sql() -> None:
    sample = (
        "**Headline Governed Answer**\n"
        "Q3 2026 Net Revenue was **RM 1,280,000.00**.\n\n"
        "- **Premium Customer Policy**: Filtered `traffic_source = 'Email'` and `age >= 35`.\n"
        "- **QA Exclusion**: Excluded `ord_stat_cd = 99`.\n\n"
        "```sql\nSELECT SUM(amt_gross_myr - disc_myr) FROM orders_raw_v2 WHERE ord_stat_cd = 1\n```"
    )
    myr, display, bullets, sql = service.extract_executive_fields(sample)
    assert myr == 1280000.0
    assert display == "RM 1,280,000.00"
    assert len(bullets) == 2
    assert "SELECT SUM(amt_gross_myr - disc_myr)" in sql


async def test_folio_endpoints_fail_closed_when_unconfigured(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "AGENT_API_KEY", None)
    monkeypatch.setattr(settings, "ENABLE_ADK_WEB_UI", False)
    res_stream = await client.post("/api/v1/agent/arena-stream", json={"prompt": "Q3 revenue?"})
    assert res_stream.status_code == 503


def test_extract_executive_fields_handles_regional_scenarios_and_fallback_sql() -> None:
    sample_kl = (
        "**Headline Answer**\n"
        "Total Kuala Lumpur Q3 Net Revenue was **RM 620,000.00**.\n\n"
        "- Excluded RM 420,000 QA load-test row (`ord_stat_cd = 99`).\n"
        "- Excluded RM 40,000 returned order (`ord_stat_cd = 2`)."
    )
    myr, display, bullets, sql = service.extract_executive_fields(
        sample_kl, fallback_sql="SELECT SUM(amt_gross_myr - disc_myr) FROM orders_raw_v2"
    )
    assert myr == 620000.0
    assert display == "RM 620,000.00"
    assert len(bullets) == 2
    assert sql == "SELECT SUM(amt_gross_myr - disc_myr) FROM orders_raw_v2"


async def test_arena_stream_endpoint_emits_sse_frames(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AGENT_API_KEY", None)
    monkeypatch.setattr(settings, "ENABLE_ADK_WEB_UI", True)

    async def fake_stream(prompt: str, user_id: str):  # type: ignore[no-untyped-def]
        yield f'data: {{"kind": "arena_done", "prompt": "{prompt}", "variance_myr": 1072500.0}}\n\n'

    monkeypatch.setattr("api.features.agent.router.stream_arena_comparison", fake_stream)
    res = await client.post("/api/v1/agent/arena-stream", json={"prompt": "  Q3 Net Revenue?  "})
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    assert '"variance_myr": 1072500.0' in res.text
