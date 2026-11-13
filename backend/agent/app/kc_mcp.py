"""Lazy Knowledge Catalog Managed Remote MCP (`dataplex.googleapis.com/mcp`) toolset builder.

Uses ADK's `header_provider` hook so zero network calls or ADC token refreshes occur at
module import time, while automatically refreshing OAuth 2.0 Bearer tokens across sessions.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import google.auth
import google.auth.credentials
import google.auth.transport.requests
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

KNOWLEDGE_CATALOG_MCP_URL = "https://dataplex.googleapis.com/mcp"
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

_cred_lock = threading.Lock()
_cached_credentials: google.auth.credentials.Credentials | None = None


def _resolve_quota_project() -> str:
    """Return the configured Google Cloud project ID for Knowledge Catalog MCP quota attribution."""
    project = (os.environ.get("GCP_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    if not project or project.startswith("<"):
        raise RuntimeError("Set GCP_PROJECT_ID in .env before calling Knowledge Catalog MCP.")
    return project


def get_knowledge_catalog_mcp_headers(_readonly_context: Any = None) -> dict[str, str]:
    """Mint or refresh Google Cloud ADC OAuth headers for `https://dataplex.googleapis.com/mcp`."""
    global _cached_credentials
    with _cred_lock:
        if _cached_credentials is None:
            creds, _ = google.auth.default(scopes=[CLOUD_PLATFORM_SCOPE])
            _cached_credentials = creds
        if not _cached_credentials.valid or _cached_credentials.expired or not _cached_credentials.token:
            _cached_credentials.refresh(google.auth.transport.requests.Request())
        token = _cached_credentials.token
    if not token:
        raise RuntimeError("Failed to obtain Google Cloud ADC OAuth token for Knowledge Catalog MCP.")
    return {
        "Authorization": f"Bearer {token}",
        "x-goog-user-project": _resolve_quota_project(),
    }


def build_knowledge_catalog_mcp_toolset() -> McpToolset:
    """Build an ADK `McpToolset` scoped to read-only Knowledge Catalog discovery & context lookup."""
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=KNOWLEDGE_CATALOG_MCP_URL,
            timeout=15.0,
            sse_read_timeout=180.0,
        ),
        tool_filter=["search_entries", "lookup_context"],
        header_provider=get_knowledge_catalog_mcp_headers,
        tool_list_cache_ttl_seconds=7200.0,
    )
