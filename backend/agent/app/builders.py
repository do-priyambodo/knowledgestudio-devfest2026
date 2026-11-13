"""Shared ADK Agent factory functions for Without-KC and With-KC comparison agents.

Keeping factories in a leaf module (`app.builders`) maintains a clean acyclic import graph:
`{app.tools, app.kc_mcp} -> app.builders -> {app.agent, agent_1_without_kc, agent_2_with_kc}`.
"""

from __future__ import annotations

import os

from google.adk.agents import Agent
from google.genai import types as genai_types

from app.kc_mcp import build_knowledge_catalog_mcp_toolset
from app.tools import (
    inspect_bigquery_schema,
    run_readonly_bigquery_sql,
)

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-4-hydrogen")
GCP_PROJECT = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "<YOUR_GCP_PROJECT_ID>"
MAX_OUTPUT_TOKENS = 32768

AGENT_GENERATION_CONFIG = genai_types.GenerateContentConfig(
    temperature=0.1,
    max_output_tokens=MAX_OUTPUT_TOKENS,
    thinking_config=genai_types.ThinkingConfig(
        thinking_level=genai_types.ThinkingLevel.LOW,
        include_thoughts=False,
    ),
)


def _active_project() -> str:
    return (os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or GCP_PROJECT).strip()


def _build_without_kc_instruction(project_id: str) -> str:
    return f"""You are a senior data analyst for Cymbal Retail Malaysia.
Your BigQuery project is `{project_id}` and your dataset is `cymbal_retail_my` (location `US`).

Workflow:
1. Inspect the physical schema first using `inspect_bigquery_schema(dataset_id="cymbal_retail_my")`.
2. Write clean, single-statement read-only GoogleSQL (`SELECT` or `WITH`) and run it using `run_readonly_bigquery_sql`.
3. Never invent or mentally calculate numbers. Always execute SQL against `{project_id}.cymbal_retail_my`.
4. Keep your response concise (under 160 words) so it fits on a single live projection screen:
   - **Headline Answer (in MYR / RM)**
   - **Assumptions Made from Schema** (2-3 short bullets on which columns/filters you chose)
   - **Executed SQL Query** (compact fenced `sql` block)
"""


def _build_with_kc_instruction(project_id: str) -> str:
    return f"""You are a senior data analyst for Cymbal Retail Malaysia, grounded in Google Cloud Knowledge Studio.
Your Google Cloud quota & data project is `{project_id}` and your BigQuery dataset is `cymbal_retail_my` (location `us`).

MANDATORY KNOWLEDGE STUDIO GROUNDING PROTOCOL (NEVER SKIP):
1. **Discover Context First (`search_entries`)**:
   - Before writing ANY SQL, call `search_entries` ONCE with `projectId="{project_id}"` and `query="cymbal_retail_my"` to discover the Context Set entries (`entryGroups/cymbal_retail_my_context_set`), policy entries (`entryGroups/cymbal_retail_my_policies`), and `@bigquery` table entries (`orders_raw_v2`, `users`).
2. **Read Governed Context in ONE Batch Call (`lookup_context`)**:
   - Collect the matching `locations/us/...` `dataplexEntry.name` resource paths from `search_entries`, prioritizing governed policy/metric entries (`*policy*`, `*metric*`, `*exclusion*`) and `@bigquery` table entries (`orders_raw_v2`, `users`) while skipping navigation folder index entries (`agents`, `assets`, `bigquery`, `documents`, `concepts`), and fetch them (up to 10 resources) in **ONE single `lookup_context` call** (`projectId="{project_id}"`, `location="us"`, `resources=[...]`). Do NOT make a second `lookup_context` call to `location="global"`.
3. **Execute Governed SQL Immediately**:
   - Strictly obey all metric formulas, canonical customer segmentation criteria, status code filters, and `DEPRECATED / DO NOT USE` column warnings returned by `lookup_context`.
   - Execute your governed query immediately with `run_readonly_bigquery_sql` (no need to call `inspect_bigquery_schema` if `lookup_context` already returned the `@bigquery` table schemas).
4. **Keep Your Response Concise (under 180 words for live stage readability)**:
   - **Headline Governed Answer (in MYR / RM)**
   - **Knowledge Studio Context Applied** (3 short bullets citing the governed Context Set rules & schema traps avoided)
   - **Executed Governed SQL Query** (compact fenced `sql` block)
"""


WITHOUT_KC_INSTRUCTION = _build_without_kc_instruction(GCP_PROJECT)
WITH_KC_INSTRUCTION = _build_with_kc_instruction(GCP_PROJECT)


def build_without_kc_agent(name: str = "agent_1_without_kc") -> Agent:
    """Construct a fresh ADK Agent instance without Knowledge Studio MCP grounding."""
    return Agent(
        name=name,
        model=DEFAULT_MODEL,
        description=(
            "Baseline BigQuery SQL analyst WITHOUT Knowledge Studio (relies solely on raw "
            "BigQuery physical table columns)."
        ),
        instruction=_build_without_kc_instruction(_active_project()),
        generate_content_config=AGENT_GENERATION_CONFIG,
        tools=[
            inspect_bigquery_schema,
            run_readonly_bigquery_sql,
        ],
    )


def build_with_kc_agent(name: str = "agent_2_with_kc") -> Agent:
    """Construct a fresh ADK Agent instance grounded via Knowledge Catalog Remote MCP."""
    return Agent(
        name=name,
        model=DEFAULT_MODEL,
        description=(
            "Context-grounded BigQuery SQL analyst POWERED BY Knowledge Studio "
            "(dataplex.googleapis.com/mcp search_entries + lookup_context)."
        ),
        instruction=_build_with_kc_instruction(_active_project()),
        generate_content_config=AGENT_GENERATION_CONFIG,
        tools=[
            build_knowledge_catalog_mcp_toolset(),
            inspect_bigquery_schema,
            run_readonly_bigquery_sql,
        ],
    )
