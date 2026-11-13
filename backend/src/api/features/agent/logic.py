"""Pure functions for the agent slice: no I/O, no model call, fully unit-testable."""

import hmac

from api.features.agent.schemas import AgentRunResponse


class PromptRejectedError(ValueError):
    """The caller's prompt is unusable; the router maps only this error to 422."""


def normalize_prompt(prompt: str) -> str:
    """Strip surrounding whitespace and reject a prompt that is blank after stripping."""
    cleaned = prompt.strip()
    if not cleaned:
        raise PromptRejectedError("prompt is blank")
    return cleaned


def api_key_matches(presented: str | None, expected: str | None) -> bool:
    """Constant-time API-key check that fails closed when either side is missing."""
    if not presented or not expected:
        return False
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


def to_response(text: str, finish_reason: str | None, tool_calls: dict[str, int]) -> AgentRunResponse:
    """Shape a validated agent turn into the public response model (copies the tool counts)."""
    return AgentRunResponse(text=text, finish_reason=finish_reason, tool_calls=dict(tool_calls))
