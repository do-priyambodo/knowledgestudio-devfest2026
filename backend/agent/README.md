# ADK Agent Suite (`knowledgestudio-devfest2026`)

Standalone `uv` package (`google-adk[mcp]>=2.11.0,<3`) exporting three selectable agents in `adk web`:

1. `agent_1_without_kc` (`agent_1_without_kc/agent.py`): Runs `gemini-4-hydrogen` with raw BigQuery physical table metadata (`inspect_bigquery_schema`) and `run_readonly_bigquery_sql` only.
2. `agent_2_with_kc` (`agent_2_with_kc/agent.py`): Runs the exact same `gemini-4-hydrogen` model and BigQuery tools, plus Google Cloud Knowledge Studio Remote MCP via `https://dataplex.googleapis.com/mcp` (`search_entries` and `lookup_context`).
3. `app` (`app/agent.py`): Head-to-Head Arena Referee wrapping both specialists concurrently via `AgentTool`.

## Local Verification

```bash
uv sync --frozen
uv run --no-sync ruff check .
uv run --no-sync mypy app
GCP_PROJECT_ID="example-gcp-project" uv run --no-sync pytest -q
```
