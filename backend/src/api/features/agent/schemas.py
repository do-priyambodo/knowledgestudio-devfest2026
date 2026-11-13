"""Request/response models for the in-process ADK agent & Executive Briefing Folio slice."""

from pydantic import BaseModel, ConfigDict, Field

MAX_PROMPT_CHARS = 8000


class AgentRunRequest(BaseModel):
    """Single-agent or side-by-side prompt execution payload."""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(..., min_length=1, max_length=MAX_PROMPT_CHARS)
    user_id: str = Field(default="anonymous", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._@-]+$")


class AgentRunResponse(BaseModel):
    """Single-agent validated turn response."""

    text: str
    finish_reason: str | None
    tool_calls: dict[str, int]


class SingleAgentResult(BaseModel):
    """Structured result for one side of the Without-KC vs. With-KC comparison."""

    model_config = ConfigDict(extra="forbid")

    agent_name: str
    text: str
    finish_reason: str | None
    tool_calls: dict[str, int]
    latency_ms: float


class AgentCompareResponse(BaseModel):
    """Side-by-side response comparing raw BigQuery schema vs. Knowledge Studio MCP."""

    model_config = ConfigDict(extra="forbid")

    prompt: str
    without_knowledgestudio: SingleAgentResult
    with_knowledgestudio: SingleAgentResult
