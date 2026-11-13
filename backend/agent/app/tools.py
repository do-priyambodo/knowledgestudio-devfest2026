"""Read-only BigQuery execution and physical schema inspection tools.

Enforces single-statement `SELECT`/`WITH` validation, 1 GiB `maximum_bytes_billed` FinOps
caps, and BigQuery job attribution labels.
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
import os
import re
import threading
from typing import Any

from google.cloud import bigquery

MAX_QUERY_BYTES_BILLED = 1_073_741_824  # 1 GiB FinOps guardrail
MAX_RETURNED_ROWS = 50
DEFAULT_DATASET_ID = "cymbal_retail_my"
DEFAULT_BQ_LOCATION = "US"

_bq_client_lock = threading.Lock()
_bq_clients: dict[str, bigquery.Client] = {}


def _get_bq_client(project_id: str) -> bigquery.Client:
    """Return a lazily initialized, keep-alive `bigquery.Client` cached per project ID."""
    with _bq_client_lock:
        client = _bq_clients.get(project_id)
        if client is None:
            client = bigquery.Client(project=project_id, location=DEFAULT_BQ_LOCATION)
            _bq_clients[project_id] = client
        return client


_DATASET_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")
_FORBIDDEN_KEYWORDS_RE = re.compile(
    r"\b(DROP|DELETE|INSERT|UPDATE|MERGE|CREATE|ALTER|TRUNCATE|GRANT|REVOKE|CALL|EXPORT|EXECUTE|LOAD)\b",
    re.IGNORECASE,
)


class ReadonlySqlViolationError(ValueError):
    """Raised when a candidate SQL string violates the single-statement read-only contract."""


def _resolve_project_id() -> str:
    """Resolve the active GCP project ID from environment configuration."""
    project = (os.environ.get("GCP_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    if not project or project.startswith("<"):
        raise RuntimeError("Set GCP_PROJECT_ID in .env before running BigQuery tools.")
    return project


def _strip_leading_sql_comments(sql: str) -> str:
    """Remove leading whitespace, `--` line comments, and `/* ... */` block comments."""
    s = sql.lstrip()
    while s:
        if s.startswith("--"):
            newline_idx = s.find("\n")
            s = "" if newline_idx == -1 else s[newline_idx + 1 :].lstrip()
        elif s.startswith("/*"):
            end_idx = s.find("*/")
            if end_idx == -1:
                raise ReadonlySqlViolationError("Unterminated block comment in SQL query.")
            s = s[end_idx + 2 :].lstrip()
        else:
            break
    return s


def _strip_quoted_literals(sql: str) -> str:
    """Replace single-quoted, double-quoted, and backticked literals so keyword checks avoid false hits."""
    return re.sub(r"('(?:''|\\'|[^'])*'|\"(?:\"\"|\\\"|[^\"])*\"|`[^`]*`)", "''", sql)


def validate_readonly_sql(sql: str) -> str:
    """Validate that `sql` is a single read-only `SELECT` or `WITH` GoogleSQL statement.

    Args:
        sql: Candidate GoogleSQL query string.

    Returns:
        Cleaned SQL string with trailing semicolons stripped.

    Raises:
        ReadonlySqlViolationError: If empty, multi-statement, or containing mutating keywords.
    """
    if not sql or not sql.strip():
        raise ReadonlySqlViolationError("SQL query must not be empty.")

    cleaned = sql.strip()
    while cleaned.endswith(";"):
        cleaned = cleaned[:-1].rstrip()

    body_after_comments = _strip_leading_sql_comments(cleaned)
    if not body_after_comments:
        raise ReadonlySqlViolationError("SQL query contains only comments.")

    unquoted = _strip_quoted_literals(body_after_comments)
    if ";" in unquoted:
        raise ReadonlySqlViolationError("Multi-statement SQL queries (embedded ';') are forbidden.")

    first_word_match = re.match(r"^([A-Za-z]+)\b", unquoted)
    first_word = first_word_match.group(1).upper() if first_word_match else ""
    if first_word not in {"SELECT", "WITH"}:
        raise ReadonlySqlViolationError(
            f"Only read-only SELECT or WITH queries are permitted (got leading keyword {first_word!r})."
        )

    forbidden_match = _FORBIDDEN_KEYWORDS_RE.search(unquoted)
    if forbidden_match:
        raise ReadonlySqlViolationError(
            f"Forbidden DML/DDL keyword {forbidden_match.group(1).upper()!r} detected in read-only SQL tool."
        )

    return cleaned


def _json_default(value: Any) -> Any:
    """Serialize BigQuery dates, timestamps, and decimals cleanly to JSON."""
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    return str(value)


def _execute_bq_query(sql: str) -> dict[str, Any]:
    """Execute a pre-validated read-only BigQuery query with byte cap and attribution labels."""
    validated_sql = validate_readonly_sql(sql)
    project_id = _resolve_project_id()
    client = _get_bq_client(project_id)
    job_config = bigquery.QueryJobConfig(
        maximum_bytes_billed=MAX_QUERY_BYTES_BILLED,
        use_legacy_sql=False,
        labels={"app": "knowledgestudio-devfest2026"},
    )
    query_job = client.query(validated_sql, job_config=job_config)
    result_iter = query_job.result(timeout=60.0)
    rows: list[dict[str, Any]] = []
    for idx, row in enumerate(result_iter):
        if idx >= MAX_RETURNED_ROWS:
            break
        rows.append(dict(row.items()))

    return {
        "project_id": project_id,
        "sql_executed": validated_sql,
        "returned_rows": len(rows),
        "total_rows": result_iter.total_rows,
        "bytes_processed": query_job.total_bytes_processed or 0,
        "rows": rows,
    }


def inspect_bigquery_schema(dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """Inspect physical table names, column names, and data types in BigQuery metadata.

    Uses BigQuery's live `tables.list` + `tables.get` metadata API (~250ms) rather than
    spinning up a multi-second SQL query job against `INFORMATION_SCHEMA`.

    Args:
        dataset_id: BigQuery dataset name inside the active project (defaults to 'cymbal_retail_my').

    Returns:
        JSON payload listing physical tables, columns, nullability, and descriptions from BigQuery.
    """
    clean_ds = dataset_id.strip() or DEFAULT_DATASET_ID
    if not _DATASET_NAME_RE.match(clean_ds):
        raise ValueError(f"Invalid BigQuery dataset identifier: {clean_ds!r}")
    project_id = _resolve_project_id()
    client = _get_bq_client(project_id)
    dataset_ref = f"{project_id}.{clean_ds}"
    rows: list[dict[str, Any]] = []
    for tbl_item in sorted(client.list_tables(dataset_ref), key=lambda t: t.table_id):
        tbl = client.get_table(tbl_item.reference)
        for pos, field in enumerate(tbl.schema, start=1):
            rows.append(
                {
                    "table_name": tbl.table_id,
                    "ordinal_position": pos,
                    "column_name": field.name,
                    "data_type": field.field_type,
                    "is_nullable": "YES" if field.is_nullable else "NO",
                    "physical_column_description": field.description,
                }
            )
    payload: dict[str, Any] = {
        "project_id": project_id,
        "dataset_id": clean_ds,
        "returned_rows": len(rows),
        "total_rows": len(rows),
        "bytes_processed": 0,
        "rows": rows,
    }
    return json.dumps(payload, default=_json_default, indent=2)


def run_readonly_bigquery_sql(sql: str) -> str:
    """Execute a single read-only GoogleSQL SELECT or WITH query against BigQuery.

    Args:
        sql: A complete GoogleSQL SELECT or WITH query using fully qualified `project.dataset.table` names.

    Returns:
        JSON string containing `sql_executed`, `rows`, `total_rows`, and `bytes_processed`.
    """
    payload = _execute_bq_query(sql)
    return json.dumps(payload, default=_json_default, indent=2)
