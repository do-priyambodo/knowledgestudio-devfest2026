"""HTTP edge of the agent & Executive Briefing Folio slice."""

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import StreamingResponse

from api.features.agent.logic import PromptRejectedError, api_key_matches, normalize_prompt
from api.features.agent.schemas import (
    AgentCompareResponse,
    AgentRunRequest,
    AgentRunResponse,
)
from api.features.agent.service import (
    AgentTimeoutError,
    AgentTurnError,
    run_agent,
    run_comparison,
    stream_arena_comparison,
)
from api.platform.config import settings
from api.platform.logger import logger

router = APIRouter(prefix="/api/v1/agent", tags=["Agent"])


def _verify_api_key(x_api_key: str | None) -> None:
    expected = settings.AGENT_API_KEY.get_secret_value() if settings.AGENT_API_KEY else None
    if expected is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Agent endpoint disabled: AGENT_API_KEY is not set.")
    if not api_key_matches(x_api_key, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid X-API-Key.")


def _verify_folio_access(x_api_key: str | None) -> None:
    """Enforce X-API-Key when configured, or require explicit ENABLE_ADK_WEB_UI demo mode; fail closed otherwise."""
    expected = settings.AGENT_API_KEY.get_secret_value() if settings.AGENT_API_KEY else None
    if expected is not None:
        if not api_key_matches(x_api_key, expected):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid X-API-Key.")
        return
    if not settings.ENABLE_ADK_WEB_UI:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Executive Folio endpoints require AGENT_API_KEY or ENABLE_ADK_WEB_UI=true.",
        )


@router.post("/run", response_model=AgentRunResponse)
async def run(
    payload: AgentRunRequest,
    x_api_key: Annotated[str | None, Header()] = None,
) -> AgentRunResponse:
    """Execute one turn against the Arena Referee orchestrator (`root_agent`)."""
    _verify_api_key(x_api_key)
    try:
        prompt = normalize_prompt(payload.prompt)
    except PromptRejectedError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    try:
        return await run_agent(prompt, payload.user_id)
    except AgentTimeoutError as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, str(exc)) from exc
    except AgentTurnError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except Exception as exc:
        logger.exception("agent run failed", feature="agent", user_id=payload.user_id, error_type=type(exc).__name__)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Agent run failed.") from exc


@router.post("/compare", response_model=AgentCompareResponse)
async def compare(
    payload: AgentRunRequest,
    x_api_key: Annotated[str | None, Header()] = None,
) -> AgentCompareResponse:
    """Run `agent_1_without_kc` and `agent_2_with_kc` concurrently for side-by-side comparison."""
    _verify_api_key(x_api_key)
    try:
        prompt = normalize_prompt(payload.prompt)
    except PromptRejectedError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    try:
        return await run_comparison(prompt, payload.user_id)
    except AgentTimeoutError as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, str(exc)) from exc
    except AgentTurnError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "agent comparison failed", feature="agent_compare", user_id=payload.user_id, error_type=type(exc).__name__
        )
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Agent comparison failed.") from exc


@router.post("/arena-stream")
async def arena_stream(
    payload: AgentRunRequest,
    x_api_key: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """Stream real-time multiplexed SSE progress & final verdicts for Exhibit A and Exhibit B."""
    _verify_folio_access(x_api_key)
    try:
        prompt = normalize_prompt(payload.prompt)
    except PromptRejectedError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    return StreamingResponse(
        stream_arena_comparison(prompt, payload.user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
