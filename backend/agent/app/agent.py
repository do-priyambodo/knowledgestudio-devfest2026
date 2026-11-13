"""Dropdown Agent 3 (`app` — Arena Referee) & Canonical ADK Runner Entry Point.

Wraps isolated instances of both `without_knowledgestudio_specialist` and
`with_knowledgestudio_specialist` via `AgentTool` so a single prompt in `adk web` (or via
FastAPI `/api/v1/agent/compare`) executes both head-to-head and renders a side-by-side
comparison scorecard.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from google.adk import Runner
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.sessions import InMemorySessionService
from google.adk.tools.agent_tool import AgentTool
from google.genai import types as genai_types

from app.builders import (
    AGENT_GENERATION_CONFIG,
    DEFAULT_MODEL,
    GCP_PROJECT,
    build_with_kc_agent,
    build_without_kc_agent,
)
from app.builders import MAX_OUTPUT_TOKENS as MAX_OUTPUT_TOKENS

GCP_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
ADK_APP_NAME = "app"


def configure_adk_environment() -> None:
    """Mirror Vertex AI settings into `os.environ` before `Runner.run_async` initializes GenAI."""
    if os.environ.get("GEMINI_API_KEY"):
        os.environ.setdefault("GOOGLE_API_KEY", os.environ["GEMINI_API_KEY"])
        os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "0")
        return
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "1")
    if GCP_PROJECT:
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", GCP_PROJECT)
    # Gemini 4 (Hydrogen / Argon) & Gemini 3.8 Flash require location='global' on Vertex AI
    if DEFAULT_MODEL.startswith(("gemini-4", "gemini-3")):
        os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
    else:
        os.environ.setdefault("GOOGLE_CLOUD_LOCATION", GCP_LOCATION)


@dataclass
class AgentTurn:
    """Structured telemetry envelope for one real Google ADK `Runner` execution."""

    text: str = ""
    finish_reason: str = "STOP"
    tool_calls: dict[str, int] = field(default_factory=dict)
    latency_ms: float = 0.0

    def assert_valid(self, required_tools: Sequence[str] = ()) -> None:
        """Reject truncated, empty, or ungrounded agent turns."""
        if self.finish_reason == "MAX_TOKENS":
            raise RuntimeError("Agent turn truncated (finish_reason == MAX_TOKENS); discarding incomplete output.")
        if not self.text or not self.text.strip():
            raise RuntimeError("Agent turn produced an empty response.")
        for tool_name in required_tools:
            if self.tool_calls.get(tool_name, 0) < 1:
                raise RuntimeError(f"Agent turn skipped required tool {tool_name!r} (calls={self.tool_calls}).")


without_knowledgestudio_specialist = build_without_kc_agent("without_knowledgestudio_specialist")
with_knowledgestudio_specialist = build_with_kc_agent("with_knowledgestudio_specialist")

ARENA_INSTRUCTION = """You are the DevFest Kuala Lumpur 2026 **Head-to-Head Arena Referee** comparing:
1. `without_knowledgestudio_specialist` — Fast `gemini-4-hydrogen` model querying raw BigQuery schemas WITHOUT Knowledge Studio.
2. `with_knowledgestudio_specialist` — Exact same `gemini-4-hydrogen` model grounded in Google Cloud Knowledge Studio via `dataplex.googleapis.com/mcp`.

When the user asks a business data question or asks to compare Without vs. With Knowledge Studio:
1. Invoke **BOTH** `without_knowledgestudio_specialist` AND `with_knowledgestudio_specialist` **in parallel in the SAME tool-call turn** with the user's exact business question so both run concurrently.
2. Synthesize a crisp **Side-by-Side Comparison Scorecard** (under 220 words):
   - Markdown comparison table (`Dimension` | `Without Knowledge Studio (Dumb Data)` | `Powered by Knowledge Studio (Grounded)`) covering Reported MYR Result, Variance / Error %, Customer Filter Used, Order Status Filter Used, and Metadata Source.
   - Show both compact SQL queries side-by-side so builders immediately spot why the ungrounded query failed.
"""

root_agent = Agent(
    name="knowledgestudio_arena_orchestrator",
    model=DEFAULT_MODEL,
    description=(
        "Head-to-Head Arena Referee that runs both `without_knowledgestudio_specialist` and "
        "`with_knowledgestudio_specialist` on the same prompt and outputs a Side-by-Side SQL & MYR Scorecard."
    ),
    instruction=ARENA_INSTRUCTION,
    generate_content_config=AGENT_GENERATION_CONFIG,
    tools=[
        AgentTool(agent=without_knowledgestudio_specialist),
        AgentTool(agent=with_knowledgestudio_specialist),
    ],
)

app = App(root_agent=root_agent, name=ADK_APP_NAME)


async def collect_agent_turn(
    target_agent: Agent,
    prompt: str,
    user_id: str = "devfest-user",
    *,
    app_name: str = ADK_APP_NAME,
) -> AgentTurn:
    """Execute one real ADK `Runner` turn and fold events into a verified `AgentTurn`."""
    configure_adk_environment()
    started = time.perf_counter()
    session_service = InMemorySessionService()
    session_id = f"session-{uuid.uuid4().hex[:12]}"
    await session_service.create_session(app_name=app_name, user_id=user_id, session_id=session_id)

    runner = Runner(agent=target_agent, app_name=app_name, session_service=session_service)
    user_msg = genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=prompt)])

    chunks: list[str] = []
    tool_calls: dict[str, int] = {}
    finish_reason = "STOP"

    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=user_msg):
        raw_fr = getattr(event, "finish_reason", None)
        if raw_fr is not None:
            fr_name = getattr(raw_fr, "name", None)
            finish_reason = str(fr_name if fr_name is not None else raw_fr)
        content = getattr(event, "content", None)
        if content and getattr(content, "parts", None):
            for part in content.parts:
                fn_call = getattr(part, "function_call", None)
                if fn_call and getattr(fn_call, "name", None):
                    tool_calls[fn_call.name] = tool_calls.get(fn_call.name, 0) + 1
                if getattr(part, "text", None) and getattr(event, "author", "") == target_agent.name:
                    chunks.append(part.text)

    latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
    return AgentTurn(
        text="\n".join(c.strip() for c in chunks if c.strip()),
        finish_reason=finish_reason,
        tool_calls=tool_calls,
        latency_ms=latency_ms,
    )


async def compare_without_vs_with_kc(prompt: str, user_id: str = "devfest-stage") -> tuple[AgentTurn, AgentTurn]:
    """Run `agent_1_without_kc` and `agent_2_with_kc` concurrently via structured TaskGroup."""
    fresh_without = build_without_kc_agent("agent_1_without_kc")
    fresh_with = build_with_kc_agent("agent_2_with_kc")
    async with asyncio.TaskGroup() as tg:
        task_without = tg.create_task(
            collect_agent_turn(fresh_without, prompt, user_id=user_id, app_name="agent_1_without_kc")
        )
        task_with = tg.create_task(collect_agent_turn(fresh_with, prompt, user_id=user_id, app_name="agent_2_with_kc"))
    return task_without.result(), task_with.result()
