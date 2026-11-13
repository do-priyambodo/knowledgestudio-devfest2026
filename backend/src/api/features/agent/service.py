"""Agent slice service: ADK Runner and live concurrent SSE Arena stream."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import google.auth
import google.auth.transport.requests
import httpx
from app.agent import AgentTurn, collect_agent_turn, compare_without_vs_with_kc, configure_adk_environment, root_agent
from app.builders import build_with_kc_agent, build_without_kc_agent
from google.adk import Runner
from google.adk.agents import Agent
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from api.features.agent.logic import to_response
from api.features.agent.schemas import (
    AgentCompareResponse,
    AgentRunResponse,
    SingleAgentResult,
)
from api.platform.config import settings
from api.platform.logger import logger

AGENT_RUNTIME_RESOURCE_RE = re.compile(
    r"^projects/[a-z][a-z0-9-]{4,28}[a-z0-9]/locations/[a-z]+-[a-z]+\d+/reasoningEngines/[A-Za-z0-9_-]+$"
)
_SQL_BLOCK_RE = re.compile(r"```(?:sql|googlesql)?\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)
_MYR_AMOUNT_RE = re.compile(r"(?:RM|MYR)\s*([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]{1,2})?|[0-9]{4,}(?:\.[0-9]{1,2})?)")

TOOL_STEP_LABELS: dict[str, str] = {
    "inspect_bigquery_schema": "Reading raw BigQuery table schema",
    "search_entries": "Searching Knowledge Catalog entries",
    "lookup_context": "Reading governed Context Set rules",
    "run_readonly_bigquery_sql": "Executing read-only BigQuery SQL",
}

type LocalCollector = Callable[[object, str, str], Awaitable[AgentTurn]]
type RemoteCaller = Callable[[str, str, str, str], Awaitable[AgentTurn]]
type PairComparator = Callable[[str, str], Awaitable[tuple[AgentTurn, AgentTurn]]]


def validate_agent_runtime_resource(resource: str | None = None) -> str | None:
    """Validate optional AGENT_RUNTIME_RESOURCE format; return None when unset."""
    raw = resource if resource is not None else os.environ.get("AGENT_RUNTIME_RESOURCE", "")
    val = raw.strip()
    if not val:
        return None
    if not AGENT_RUNTIME_RESOURCE_RE.match(val):
        raise ValueError(f"Malformed AGENT_RUNTIME_RESOURCE: {val}")
    return val


def extract_executive_fields(raw_text: str, fallback_sql: str = "") -> tuple[float | None, str | None, list[str], str]:
    """Parse MYR figure, formatted MYR display, clean executive bullets, and SQL from an ADK response."""
    sql_match = _SQL_BLOCK_RE.search(raw_text)
    extracted_sql = sql_match.group(1).strip() if sql_match else fallback_sql.strip()
    prose_without_sql = _SQL_BLOCK_RE.sub("", raw_text)

    headline_myr: float | None = None
    headline_display: str | None = None
    myr_match = _MYR_AMOUNT_RE.search(prose_without_sql)
    if myr_match:
        numeric_str = myr_match.group(1).replace(",", "")
        try:
            headline_myr = round(float(numeric_str), 2)
            headline_display = f"RM {headline_myr:,.2f}"
        except ValueError:
            headline_myr = None

    bullets: list[str] = []
    for raw_line in prose_without_sql.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith(("- ", "* ", "• ")):
            item = stripped[2:].strip()
            clean_item = re.sub(r"\*\*([^*]+)\*\*", r"\1", item)
            if clean_item and len(bullets) < 4:
                bullets.append(clean_item)

    if not bullets:
        for raw_line in prose_without_sql.splitlines():
            stripped = re.sub(r"\*\*([^*]+)\*\*", r"\1", raw_line.strip())
            if (
                stripped
                and not stripped.startswith("#")
                and not stripped.lower().startswith(("headline", "assumptions", "knowledge studio", "executed"))
                and len(stripped) > 24
                and len(bullets) < 3
            ):
                bullets.append(stripped)

    return headline_myr, headline_display, bullets, extracted_sql


async def _query_remote_agent_runtime(
    resource: str,
    user_id: str,
    session_id: str,
    message: str,
) -> AgentTurn:
    """Invoke a deployed Vertex AI Agent Runtime (ReasoningEngine) over REST."""
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    req = google.auth.transport.requests.Request()
    credentials.refresh(req)

    parts = resource.split("/")
    location = parts[3]
    url = f"https://{location}-aiplatform.googleapis.com/v1beta1/{resource}:query"

    payload = {
        "input": {
            "user_id": user_id,
            "session_id": session_id,
            "new_message": message,
        }
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {credentials.token}"},
            json=payload,
            timeout=settings.AGENT_TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()

    output = data if isinstance(data, dict) and "text" in data else data.get("output", {})
    if not isinstance(output, dict):
        output = {"text": str(output)}

    turn = AgentTurn()
    turn.text = str(output.get("text", ""))
    finish_reason = output.get("finish_reason")
    turn.finish_reason = str(finish_reason) if finish_reason is not None else "STOP"
    raw_tools = output.get("tool_calls", {})
    if isinstance(raw_tools, dict):
        turn.tool_calls = {str(k): int(v) for k, v in raw_tools.items()}
    return turn


class AgentTurnError(RuntimeError):
    """The agent ran but its turn failed validation (truncated, empty, or ungrounded)."""


class AgentTimeoutError(RuntimeError):
    """The agent turn did not finish within AGENT_TIMEOUT_S."""


async def run_agent(
    prompt: str,
    user_id: str,
    *,
    local_collector: LocalCollector | None = None,
    remote_caller: RemoteCaller | None = None,
) -> AgentRunResponse:
    """Run one turn for an already-normalized prompt (see logic.normalize_prompt)."""
    started = time.perf_counter()
    log = logger.bind(feature="agent", user_id=user_id, prompt_chars=len(prompt))
    log.info("agent turn started")

    runtime_resource = validate_agent_runtime_resource()
    turn: AgentTurn

    try:
        if runtime_resource is None:
            collector = local_collector or collect_agent_turn
            turn = await asyncio.wait_for(
                collector(root_agent, prompt, user_id),
                timeout=settings.AGENT_TIMEOUT_S,
            )
        else:
            caller = remote_caller or _query_remote_agent_runtime
            turn = await asyncio.wait_for(
                caller(runtime_resource, user_id, user_id, prompt),
                timeout=settings.AGENT_TIMEOUT_S,
            )
    except TimeoutError as exc:
        log.error("agent turn timed out", timeout_s=settings.AGENT_TIMEOUT_S)
        raise AgentTimeoutError(f"agent turn exceeded {settings.AGENT_TIMEOUT_S}s") from exc

    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    try:
        turn.assert_valid()
    except RuntimeError as exc:
        log.error("agent turn rejected", reason=str(exc), latency_ms=latency_ms, tool_calls=turn.tool_calls)
        raise AgentTurnError(str(exc)) from exc

    log.info(
        "agent turn completed", latency_ms=latency_ms, finish_reason=turn.finish_reason, tool_calls=turn.tool_calls
    )
    return to_response(turn.text, turn.finish_reason, turn.tool_calls)


async def run_comparison(
    prompt: str,
    user_id: str,
    *,
    comparator: PairComparator | None = None,
) -> AgentCompareResponse:
    """Execute `agent_1_without_kc` and `agent_2_with_kc` concurrently for side-by-side UI comparison."""
    log = logger.bind(feature="agent_compare", user_id=user_id, prompt_chars=len(prompt))
    log.info("agent side-by-side comparison started")
    runner_fn = comparator or compare_without_vs_with_kc
    try:
        without_turn, with_turn = await asyncio.wait_for(
            runner_fn(prompt, user_id),
            timeout=settings.AGENT_TIMEOUT_S,
        )
    except TimeoutError as exc:
        log.error("agent comparison timed out", timeout_s=settings.AGENT_TIMEOUT_S)
        raise AgentTimeoutError(f"agent comparison exceeded {settings.AGENT_TIMEOUT_S}s") from exc

    try:
        without_turn.assert_valid()
        with_turn.assert_valid()
    except RuntimeError as exc:
        log.error("agent comparison turn rejected", reason=str(exc))
        raise AgentTurnError(str(exc)) from exc

    return AgentCompareResponse(
        prompt=prompt,
        without_knowledgestudio=SingleAgentResult(
            agent_name="agent_1_without_kc",
            text=without_turn.text,
            finish_reason=without_turn.finish_reason,
            tool_calls=dict(without_turn.tool_calls),
            latency_ms=without_turn.latency_ms,
        ),
        with_knowledgestudio=SingleAgentResult(
            agent_name="agent_2_with_kc",
            text=with_turn.text,
            finish_reason=with_turn.finish_reason,
            tool_calls=dict(with_turn.tool_calls),
            latency_ms=with_turn.latency_ms,
        ),
    )


async def _run_single_lane_into_queue(
    lane: str,
    target_agent: Agent,
    app_name: str,
    prompt: str,
    user_id: str,
    started_at: float,
    queue: asyncio.Queue[dict[str, Any]],
    results_out: dict[str, float | None],
) -> None:
    """Stream one ADK specialist's tool calls and final answer into the shared SSE queue."""
    await queue.put(
        {
            "kind": "lane_start",
            "lane": lane,
            "agent_name": app_name,
            "model": str(target_agent.model),
            "elapsed_ms": round((time.perf_counter() - started_at) * 1000.0, 1),
        }
    )
    session_service = InMemorySessionService()
    session_id = f"folio-{lane}-{uuid.uuid4().hex[:10]}"
    await session_service.create_session(app_name=app_name, user_id=user_id, session_id=session_id)
    runner = Runner(agent=target_agent, app_name=app_name, session_service=session_service)
    user_msg = genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=prompt)])

    visible_chunks: list[str] = []
    tool_calls: dict[str, int] = {}
    last_sql_arg = ""
    finish_reason = "STOP"

    try:
        async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=user_msg):
            now_ms = round((time.perf_counter() - started_at) * 1000.0, 1)
            raw_fr = getattr(event, "finish_reason", None)
            if raw_fr is not None:
                fr_name = getattr(raw_fr, "name", None)
                finish_reason = str(fr_name if fr_name is not None else raw_fr)

            content = getattr(event, "content", None)
            if not content or not getattr(content, "parts", None):
                continue

            for part in content.parts:
                fn_call = getattr(part, "function_call", None)
                if fn_call and getattr(fn_call, "name", None):
                    t_name = str(fn_call.name)
                    tool_calls[t_name] = tool_calls.get(t_name, 0) + 1
                    args_dict = dict(getattr(fn_call, "args", None) or {})
                    if t_name == "run_readonly_bigquery_sql" and isinstance(args_dict.get("sql"), str):
                        last_sql_arg = args_dict["sql"]
                    await queue.put(
                        {
                            "kind": "tool_call",
                            "lane": lane,
                            "tool": t_name,
                            "label": TOOL_STEP_LABELS.get(t_name, f"Calling {t_name}"),
                            "elapsed_ms": now_ms,
                        }
                    )

                fn_resp = getattr(part, "function_response", None)
                if fn_resp and getattr(fn_resp, "name", None):
                    r_name = str(fn_resp.name)
                    await queue.put(
                        {
                            "kind": "tool_result",
                            "lane": lane,
                            "tool": r_name,
                            "elapsed_ms": now_ms,
                        }
                    )

                is_thought = bool(getattr(part, "thought", False))
                txt = getattr(part, "text", None)
                if txt and not is_thought and getattr(event, "author", "") == target_agent.name:
                    visible_chunks.append(str(txt))

        clean_text = "\n".join(c.strip() for c in visible_chunks if c.strip())
        turn_check = AgentTurn(text=clean_text, finish_reason=finish_reason, tool_calls=tool_calls)
        turn_check.assert_valid()

        headline_myr, headline_display, bullets, sql_str = extract_executive_fields(clean_text, last_sql_arg)
        results_out[lane] = headline_myr
        await queue.put(
            {
                "kind": "lane_final",
                "lane": lane,
                "headline_myr": headline_myr,
                "headline_display": headline_display,
                "bullets": bullets,
                "sql": sql_str,
                "raw_text": clean_text,
                "tool_calls": tool_calls,
                "elapsed_ms": round((time.perf_counter() - started_at) * 1000.0, 1),
            }
        )
    except Exception as exc:
        logger.exception("arena lane failed", lane=lane, error_type=type(exc).__name__)
        await queue.put(
            {
                "kind": "lane_error",
                "lane": lane,
                "message": "Verification halted — upstream BigQuery or Knowledge Catalog call failed.",
                "elapsed_ms": round((time.perf_counter() - started_at) * 1000.0, 1),
            }
        )


async def stream_arena_comparison(prompt: str, user_id: str) -> AsyncIterator[str]:
    """Yield multiplexed SSE `data: {...}\\n\\n` frames as both ADK specialists race concurrently."""
    configure_adk_environment()
    started = time.perf_counter()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    results_out: dict[str, float | None] = {"without_kc": None, "with_kc": None}

    agent_without = build_without_kc_agent("agent_1_without_kc")
    agent_with = build_with_kc_agent("agent_2_with_kc")

    async def _orchestrate() -> None:
        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(
                    _run_single_lane_into_queue(
                        "without_kc",
                        agent_without,
                        "agent_1_without_kc",
                        prompt,
                        user_id,
                        started,
                        queue,
                        results_out,
                    )
                )
                tg.create_task(
                    _run_single_lane_into_queue(
                        "with_kc",
                        agent_with,
                        "agent_2_with_kc",
                        prompt,
                        user_id,
                        started,
                        queue,
                        results_out,
                    )
                )
        finally:
            m_without = results_out.get("without_kc")
            m_with = results_out.get("with_kc")
            variance_myr: float | None = None
            variance_pct: float | None = None
            if m_without is not None and m_with is not None and m_with > 0:
                variance_myr = round(m_without - m_with, 2)
                variance_pct = round(((m_without - m_with) / m_with) * 100.0, 1)
            await queue.put(
                {
                    "kind": "arena_done",
                    "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
                    "variance_myr": variance_myr,
                    "variance_pct": variance_pct,
                }
            )

    orchestrator_task = asyncio.create_task(_orchestrate())
    try:
        while True:
            frame = await asyncio.wait_for(queue.get(), timeout=settings.AGENT_TIMEOUT_S)
            yield f"data: {json.dumps(frame)}\n\n"
            if frame.get("kind") == "arena_done":
                break
        await orchestrator_task
    finally:
        if not orchestrator_task.done():
            orchestrator_task.cancel()
