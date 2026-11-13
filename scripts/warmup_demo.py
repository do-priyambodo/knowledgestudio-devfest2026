#!/usr/bin/env python3
"""Pre-stage warmup utility for the live `adk web` server (`:8081` or `:8080`).

Sends a lightweight live turn through `agent_1_without_kc` and `agent_2_with_kc` on the
running ADK Web Playground HTTP server so its in-process memory pre-warms:
1. Google Cloud ADC OAuth 2.0 Bearer tokens (`kc_mcp.py`)
2. Knowledge Catalog MCP (`https://dataplex.googleapis.com/mcp`) 2-hour `tools/list` cache
3. Singleton `bigquery.Client` HTTP/2 keep-alive connection pool (`tools.py`)
4. Vertex AI `gemini-4-hydrogen` global endpoint connection

Automatically deletes its temporary warmup sessions afterward so the `adk web` session
sidebar stays completely clean on stage.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Any

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("warmup_demo")

WARMUP_PROMPT = "What was our Q3 2026 Net Revenue from Premium Customers in Malaysia?"


def _validate_base_url(base_url: str) -> str:
    parsed = urllib.parse.urlparse(base_url.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid ADK Web base URL: {base_url!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


def _http_json(
    base_url: str, method: str, path: str, body: dict[str, Any] | None = None
) -> Any:
    url = f"{base_url}{path}"
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90.0) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw.strip() else {}


def _warm_single_app(base_url: str, app_name: str) -> tuple[str, float, list[str]]:
    t0 = time.perf_counter()
    user_id = "prestage-warmup"
    sess = _http_json(
        base_url, "POST", f"/apps/{app_name}/users/{user_id}/sessions", {}
    )
    session_id = str(sess["id"])
    tool_calls: list[str] = []
    try:
        events = _http_json(
            base_url,
            "POST",
            "/run",
            {
                "appName": app_name,
                "userId": user_id,
                "sessionId": session_id,
                "newMessage": {"role": "user", "parts": [{"text": WARMUP_PROMPT}]},
                "streaming": False,
            },
        )
        for ev in events:
            parts = (ev.get("content") or {}).get("parts") or []
            for p in parts:
                fn = p.get("functionCall") or p.get("function_call")
                if fn and fn.get("name"):
                    tool_calls.append(str(fn["name"]))
    finally:
        try:
            _http_json(
                base_url,
                "DELETE",
                f"/apps/{app_name}/users/{user_id}/sessions/{session_id}",
            )
        except (OSError, ValueError):
            log.warning("Could not delete temporary warmup session %s", session_id)

    elapsed = time.perf_counter() - t0
    return app_name, elapsed, tool_calls


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-warm live ADK Web Playground caches before going on stage."
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8081",
        help="Base URL of the running ADK Web Playground server (default: http://127.0.0.1:8081).",
    )
    args = parser.parse_args()
    base_url = _validate_base_url(args.url)

    apps_resp = _http_json(base_url, "GET", "/list-apps?detailed=true")
    registered = [a["name"] for a in apps_resp.get("apps", [])]
    log.info("Connected to %s — registered apps: %s", base_url, registered)

    targets = [a for a in ("agent_1_without_kc", "agent_2_with_kc") if a in registered]
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_warm_single_app, base_url, app_name) for app_name in targets
        ]
        for fut in concurrent.futures.as_completed(futures):
            app_name, elapsed, calls = fut.result()
            log.info(
                "Warmed %-20s in %.2fs (tools=%s; 2-hour MCP & BQ caches hot)",
                app_name,
                elapsed,
                calls,
            )

    log.info(
        "Pre-stage warmup complete in %.2fs — temporary sessions cleaned up!",
        time.perf_counter() - started,
    )


if __name__ == "__main__":
    main()
