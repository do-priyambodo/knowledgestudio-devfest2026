# Backend Service (`knowledgestudio-devfest2026`)

FastAPI SSE backend and optional mounted Google ADK Web Playground (`ENABLE_ADK_WEB_UI=true`) for running `agent_1_without_kc` and `agent_2_with_kc` concurrently side-by-side.

## Endpoints

1. `GET /health`: Service readiness check.
2. `POST /api/v1/agent/arena-stream`: Streams live Server-Sent Events (`text/event-stream`) from `agent_1_without_kc` and `agent_2_with_kc` executing concurrently via `asyncio.TaskGroup`.
3. `POST /api/v1/agent/compare`: Returns a single JSON payload comparing both agents head-to-head.
4. `POST /api/v1/agent/run`: Executes a single turn on the Arena Referee (`root_agent`).
5. `/dev-ui/` (when `ENABLE_ADK_WEB_UI=true`): Interactive Google ADK Web Playground hosting all 3 dropdown agents (`agent_1_without_kc`, `agent_2_with_kc`, and `app`).

## Local Verification

```bash
uv sync --frozen
uv run --no-sync ruff check .
uv run --no-sync mypy src
GCP_PROJECT_ID="example-gcp-project" uv run --no-sync pytest -q
```
