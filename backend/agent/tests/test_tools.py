"""Unit tests for SQL safety guardrails and Knowledge Catalog MCP toolset wiring."""

from __future__ import annotations

import pytest
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

from app.kc_mcp import KNOWLEDGE_CATALOG_MCP_URL, build_knowledge_catalog_mcp_toolset
from app.tools import MAX_QUERY_BYTES_BILLED, ReadonlySqlViolationError, validate_readonly_sql


@pytest.mark.parametrize(
    "valid_sql",
    [
        "SELECT COUNT(*) FROM `example-gcp-project.cymbal_retail_my.users`",
        "  select user_id, age from cymbal_retail_my.users where age >= 35;  ",
        "WITH vip AS (SELECT user_id FROM users) SELECT COUNT(*) FROM vip",
        "-- leading comment\nSELECT SUM(amt_gross_myr - disc_myr) FROM orders_raw_v2 WHERE ord_stat_cd = 1",
        "/* block comment */ WITH t AS (SELECT 1 AS x) SELECT x FROM t;",
    ],
)
def test_validate_readonly_sql_accepts_safe_queries(valid_sql: str) -> None:
    """Safe SELECT and WITH queries pass validation with trailing semicolons stripped."""
    cleaned = validate_readonly_sql(valid_sql)
    assert cleaned
    assert not cleaned.endswith(";")


@pytest.mark.parametrize(
    "unsafe_sql",
    [
        "",
        "   ",
        "DROP TABLE cymbal_retail_my.users",
        "DELETE FROM cymbal_retail_my.orders_raw_v2 WHERE 1=1",
        "UPDATE cymbal_retail_my.users SET age = 99",
        "INSERT INTO cymbal_retail_my.users VALUES ('u99')",
        "CREATE OR REPLACE TABLE cymbal_retail_my.hack AS SELECT 1",
        "MERGE cymbal_retail_my.users t USING cymbal_retail_my.users s ON FALSE WHEN NOT MATCHED THEN INSERT ROW",
        "TRUNCATE TABLE cymbal_retail_my.orders_raw_v2",
        "CALL cymbal_retail_my.sp_admin()",
        "EXPORT DATA OPTIONS(uri='gs://bucket/*') AS SELECT * FROM users",
        "SELECT 1; DROP TABLE users",
        "/* sneak */ DELETE FROM cymbal_retail_my.users",
        "WITH x AS (SELECT 1) DELETE FROM users",
    ],
)
def test_validate_readonly_sql_rejects_mutations_and_multistatement(unsafe_sql: str) -> None:
    """Any mutating keyword, empty query, or multi-statement semicolon is rejected closed."""
    with pytest.raises(ReadonlySqlViolationError):
        validate_readonly_sql(unsafe_sql)


def test_finops_byte_cap_is_one_gib() -> None:
    """BigQuery FinOps guardrail caps per-query scan at 1 GiB."""
    assert MAX_QUERY_BYTES_BILLED == 1_073_741_824


def test_kc_mcp_toolset_builds_lazily_without_network() -> None:
    """McpToolset initializes with zero network calls, 2-hour schema cache, and read-only filter."""
    toolset = build_knowledge_catalog_mcp_toolset()
    assert isinstance(toolset, McpToolset)
    assert isinstance(toolset._connection_params, StreamableHTTPConnectionParams)
    assert toolset._connection_params.url == KNOWLEDGE_CATALOG_MCP_URL
    assert toolset.tool_filter == ["search_entries", "lookup_context"]
    assert toolset._header_provider is not None
    assert toolset._tool_list_cache_ttl_seconds == 7200.0
