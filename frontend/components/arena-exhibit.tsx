"use client";

import { useEffect, useRef, useState } from "react";
import { ErrorState } from "@/components/states";
import { cn } from "@/lib/utils";

interface StepEvent {
  tool: string;
  label: string;
  elapsedMs: number;
}

interface LaneState {
  status: "idle" | "running" | "done" | "error";
  activeLabel: string;
  steps: StepEvent[];
  headlineMyr: number | null;
  headlineDisplay: string | null;
  bullets: string[];
  sql: string;
  rawText: string;
  toolCalls: Record<string, number>;
  elapsedMs: number;
  errorMessage?: string;
}

const INITIAL_LANE: LaneState = {
  status: "idle",
  activeLabel: "",
  steps: [],
  headlineMyr: null,
  headlineDisplay: null,
  bullets: [],
  sql: "",
  rawText: "",
  toolCalls: {},
  elapsedMs: 0,
};

interface PresetScenario {
  label: string;
  prompt: string;
}

const PRESETS: readonly PresetScenario[] = [
  {
    label: "Q3 Malaysia Premium Revenue",
    prompt: "What was our Q3 2026 Net Revenue from Premium Customers in Malaysia?",
  },
  {
    label: "Kuala Lumpur Total Revenue",
    prompt: "What was our total Q3 2026 Net Revenue across all customers in Kuala Lumpur?",
  },
  {
    label: "Penang Premium Revenue",
    prompt: "What was our Q3 2026 Net Revenue from Premium Customers in Penang?",
  },
  {
    label: "Mobile App Premium Revenue",
    prompt:
      "What was our Q3 2026 Net Revenue from Premium Customers on the Mobile_App channel in Malaysia?",
  },
  {
    label: "Selangor Premium Cohort",
    prompt: "What was our Q3 2026 Net Revenue from Premium Customers in Selangor?",
  },
];

const AGENT_WITHOUT_MCP_CODE = `from google.adk.agents import Agent
from app.tools import (
    inspect_bigquery_schema,
    run_readonly_bigquery_sql,
)

WITHOUT_KC_INSTRUCTION = """
You are a senior data analyst for Cymbal Retail Malaysia.
BigQuery dataset: \`<YOUR_GCP_PROJECT_ID>.cymbal_retail_my\`.

1. Inspect the physical schema using \`inspect_bigquery_schema\`.
2. Write read-only GoogleSQL and run \`run_readonly_bigquery_sql\`.
3. Never invent numbers — always execute SQL on BigQuery.
4. Return: Headline Answer (MYR), Schema Assumptions, Executed SQL.
"""

agent_1_without_kc = Agent(
    name="agent_1_without_kc",
    model=DEFAULT_MODEL,
    instruction=WITHOUT_KC_INSTRUCTION,
    tools=[
        # No Knowledge Studio MCP context attached
        inspect_bigquery_schema,
        run_readonly_bigquery_sql,
    ],
)`;

const AGENT_WITH_MCP_CODE = `from google.adk.agents import Agent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StreamableHTTPConnectionParams,
)

WITH_KC_INSTRUCTION = """
You are a senior data analyst for Cymbal Retail Malaysia,
grounded in Google Cloud Knowledge Studio.
BigQuery dataset: \`<YOUR_GCP_PROJECT_ID>.cymbal_retail_my\`.

1. Discover Context First: call \`search_entries\` to find governed
   Context Set policies, metrics, and \`@bigquery\` table entries.
2. Read Governed Context: call \`lookup_context\` to retrieve the
   certified metric formulas, segmentation rules, and warnings.
3. Obey all governed rules and run \`run_readonly_bigquery_sql\`.
4. Return: Governed Answer (MYR), Context Applied, Executed SQL.
"""

kc_mcp = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="https://dataplex.googleapis.com/mcp",
    ),
    tool_filter=["search_entries", "lookup_context"],
    header_provider=get_knowledge_catalog_mcp_headers,
)

agent_2_with_kc = Agent(
    name="agent_2_with_kc",
    model=DEFAULT_MODEL,
    instruction=WITH_KC_INSTRUCTION,
    tools=[
        kc_mcp,  # <-- Governed Knowledge Studio MCP context
        inspect_bigquery_schema,
        run_readonly_bigquery_sql,
    ],
)`;

function formatMoneyDelta(delta: number): string {
  const sign = delta >= 0 ? "+" : "-";
  return `${sign}RM ${Math.abs(delta).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function ArenaExhibit() {
  const [prompt, setPrompt] = useState<string>("");
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [liveClockS, setLiveClockS] = useState<number>(0);
  const [withoutLane, setWithoutLane] = useState<LaneState>(INITIAL_LANE);
  const [withLane, setWithLane] = useState<LaneState>(INITIAL_LANE);
  const [varianceMyr, setVarianceMyr] = useState<number | null>(null);
  const [variancePct, setVariancePct] = useState<number | null>(null);
  const [totalElapsedMs, setTotalElapsedMs] = useState<number | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [showProof, setShowProof] = useState<boolean>(false);
  const [showCodeSample, setShowCodeSample] = useState<boolean>(false);

  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!isRunning) return;
    const t0 = performance.now();
    const id = window.setInterval(() => {
      setLiveClockS((performance.now() - t0) / 1000);
    }, 100);
    return () => window.clearInterval(id);
  }, [isRunning]);

  async function handleRun() {
    const activePrompt = prompt.trim();
    if (!activePrompt || isRunning) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setStreamError(null);
    setVarianceMyr(null);
    setVariancePct(null);
    setTotalElapsedMs(null);
    setLiveClockS(0);
    setIsRunning(true);
    setWithoutLane({
      ...INITIAL_LANE,
      status: "running",
      activeLabel: "Initializing ungrounded BigQuery session",
    });
    setWithLane({
      ...INITIAL_LANE,
      status: "running",
      activeLabel: "Connecting to Knowledge Studio MCP",
    });

    try {
      const res = await fetch("/api/arena/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: activePrompt, user_id: "devfest-kl-stage" }),
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        const errJson = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(errJson.detail || `Verification returned HTTP ${res.status}.`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const events = buffer.split("\n\n");
        buffer = events.pop() ?? "";

        for (const rawBlock of events) {
          const dataLine = rawBlock
            .split("\n")
            .find((ln) => ln.startsWith("data:"));
          if (!dataLine) continue;
          const payload = JSON.parse(dataLine.slice(5).trim()) as Record<string, unknown>;
          const kind = String(payload.kind || "");
          const lane = String(payload.lane || "");
          const setter = lane === "without_kc" ? setWithoutLane : setWithLane;

          if (kind === "tool_call") {
            const label = String(payload.label || payload.tool || "Running tool");
            const tool = String(payload.tool || "");
            const elapsedMs = Number(payload.elapsed_ms || 0);
            setter((prev) => ({
              ...prev,
              activeLabel: label,
              steps: [...prev.steps, { tool, label, elapsedMs }],
            }));
          } else if (kind === "lane_final") {
            setter((prev) => ({
              ...prev,
              status: "done",
              activeLabel: "Verification complete",
              headlineMyr:
                typeof payload.headline_myr === "number" ? payload.headline_myr : null,
              headlineDisplay:
                typeof payload.headline_display === "string"
                  ? payload.headline_display
                  : null,
              bullets: Array.isArray(payload.bullets)
                ? payload.bullets.map((b) => String(b))
                : [],
              sql: String(payload.sql || ""),
              rawText: String(payload.raw_text || ""),
              toolCalls: (payload.tool_calls as Record<string, number>) || {},
              elapsedMs: Number(payload.elapsed_ms || 0),
            }));
          } else if (kind === "lane_error") {
            setter((prev) => ({
              ...prev,
              status: "error",
              errorMessage: String(
                payload.message || "Upstream BigQuery or Knowledge Catalog error.",
              ),
              elapsedMs: Number(payload.elapsed_ms || 0),
            }));
          } else if (kind === "arena_done") {
            setTotalElapsedMs(Number(payload.elapsed_ms || 0));
            if (typeof payload.variance_myr === "number") {
              setVarianceMyr(payload.variance_myr);
            }
            if (typeof payload.variance_pct === "number") {
              setVariancePct(payload.variance_pct);
            }
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setStreamError(
          err instanceof Error
            ? err.message
            : "Verification halted — upstream service did not respond.",
        );
      }
    } finally {
      setIsRunning(false);
    }
  }

  const bothDone = withoutLane.status === "done" && withLane.status === "done";

  return (
    <div className="flex flex-col gap-6">
      {/* Executive Question Bar */}
      <section
        aria-label="Executive question input"
        className="rounded-ui border border-rule bg-surface-1 p-5"
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void handleRun();
          }}
          className="flex flex-col gap-3"
        >
          <div className="flex items-center justify-between gap-4">
            <label
              htmlFor="folio-question"
              className="text-xs font-semibold uppercase tracking-[0.08em] text-ink-2"
            >
              Boardroom inquiry
            </label>
            <span className="font-mono text-xs text-ink-2 tabular-nums">
              {isRunning
                ? `Running · ${liveClockS.toFixed(1)}s`
                : totalElapsedMs !== null
                  ? `Verified in ${(totalElapsedMs / 1000).toFixed(1)}s`
                  : "Ready · Parallel execution"}
            </span>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row">
            <input
              ref={inputRef}
              id="folio-question"
              type="text"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              disabled={isRunning}
              className="flex-1 rounded-ui border border-rule bg-surface-0 px-4 py-3 text-base text-ink-1 placeholder:text-ink-2"
              placeholder="Type a business question manually, or choose a sample question below..."
            />
            {prompt.length > 0 && !isRunning ? (
              <button
                type="button"
                onClick={() => {
                  setPrompt("");
                  inputRef.current?.focus();
                }}
                className="rounded-ui border border-rule bg-surface-2 px-4 py-3 text-sm font-medium text-ink-2 transition-[background-color,color] duration-(--dur-fast) ease-out hover:text-ink-1"
              >
                Clear
              </button>
            ) : null}
            <button
              type="submit"
              disabled={isRunning || !prompt.trim()}
              className={cn(
                "rounded-ui border border-ink-1 bg-ink-1 px-6 py-3 text-sm font-medium tracking-wide text-surface-1",
                "transition-[background-color,border-color] duration-(--dur-fast) ease-out",
                "disabled:cursor-not-allowed disabled:opacity-50",
              )}
            >
              {isRunning ? `Verifying · ${liveClockS.toFixed(1)}s` : "Verify side-by-side"}
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <span className="text-xs font-medium text-ink-2">Sample questions:</span>
            {PRESETS.map((preset) => {
              const selected = prompt.trim() === preset.prompt;
              return (
                <button
                  key={preset.label}
                  type="button"
                  disabled={isRunning}
                  onClick={() => {
                    setPrompt(preset.prompt);
                    inputRef.current?.focus();
                  }}
                  className={cn(
                    "rounded-ui border px-3 py-1.5 text-xs font-medium",
                    "transition-[background-color,border-color,color] duration-(--dur-fast) ease-out",
                    selected
                      ? "border-accent bg-surface-2 text-accent"
                      : "border-rule bg-surface-2 text-ink-1 hover:border-ink-2",
                    "disabled:opacity-50",
                  )}
                >
                  {preset.label}
                </button>
              );
            })}
          </div>
        </form>
      </section>

      {streamError ? (
        <ErrorState
          title="Verification halted"
          description={streamError}
        />
      ) : null}

      {/* Signature Element: Boardroom Variance Ribbon */}
      {bothDone && varianceMyr !== null && Math.abs(varianceMyr) > 0.01 ? (
        <section
          aria-live="polite"
          className="flex flex-col justify-between gap-3 border-y-2 border-ink-1 bg-surface-2 px-6 py-4 md:flex-row md:items-center"
        >
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-negative">
              Boardroom variance isolated
            </p>
            <p className="font-display text-2xl font-semibold text-ink-1 tabular-nums">
              {formatMoneyDelta(varianceMyr)} ungrounded distortion
              {variancePct !== null ? ` (${variancePct > 0 ? "+" : ""}${variancePct}% vs. governed truth)` : ""}
            </p>
          </div>
          <p className="max-w-md text-xs leading-relaxed text-ink-2">
            Same model, identical BigQuery tables, zero ETL changes. Only the governed Knowledge
            Studio context differed.
          </p>
        </section>
      ) : null}

      {/* Side-by-Side Deposition Folios: Exhibit A vs. Exhibit B */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* EXHIBIT A — WITHOUT KNOWLEDGE STUDIO */}
        <article
          aria-label="Exhibit A: Without Knowledge Studio"
          className="flex flex-col justify-between rounded-ui border border-rule border-t-[3px] border-t-ink-2 bg-surface-1"
        >
          <div>
            <header className="flex items-baseline justify-between gap-2 border-b border-rule bg-surface-2 px-6 py-3.5">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-ink-2">
                  Exhibit A · Without Knowledge Studio
                </p>
                <h2 className="font-display text-lg font-semibold text-ink-1">
                  Raw BigQuery Schema Only
                </h2>
              </div>
              <span className="font-mono text-xs text-ink-2">
                Descriptions: NULL
              </span>
            </header>

            <div className="p-6 sm:p-7">
              {withoutLane.status === "idle" ? (
                <div className="py-8">
                  <p className="text-sm leading-relaxed text-ink-2">
                    Queries physical table schemas directly. Because column descriptions are
                    blank, the model must guess what{" "}
                    <span className="font-mono text-ink-1">Premium Customer</span> and{" "}
                    <span className="font-mono text-ink-1">Net Revenue</span> mean from raw
                    column names.
                  </p>
                </div>
              ) : null}

              {withoutLane.status === "running" ? (
                <div role="status" aria-live="polite" className="flex flex-col gap-3 py-8">
                  <p className="text-xs font-semibold uppercase tracking-[0.08em] text-ink-2">
                    In progress · {liveClockS.toFixed(1)}s
                  </p>
                  <p className="font-display text-xl text-ink-1">
                    {withoutLane.activeLabel}...
                  </p>
                  <ol className="flex flex-col gap-1.5 border-l border-rule pl-4 font-mono text-xs text-ink-2">
                    {withoutLane.steps.map((s, idx) => (
                      <li key={`${s.tool}-${idx}`} className="tabular-nums">
                        +{(s.elapsedMs / 1000).toFixed(1)}s · {s.tool}
                      </li>
                    ))}
                  </ol>
                </div>
              ) : null}

              {withoutLane.status === "error" ? (
                <ErrorState
                  title="Exhibit A failed"
                  description={withoutLane.errorMessage}
                />
              ) : null}

              {withoutLane.status === "done" ? (
                <div className="flex flex-col gap-5">
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-negative">
                      Unverified · Schema trap contamination
                    </p>
                    <p className="mt-1 font-display text-4xl font-semibold tracking-tight text-negative tabular-nums sm:text-[42px]">
                      {withoutLane.headlineDisplay ?? "Figure reported below"}
                    </p>
                    <p className="mt-1 font-mono text-xs text-ink-2 tabular-nums">
                      {(withoutLane.elapsedMs / 1000).toFixed(1)}s · Zero context lookups ·{" "}
                      {Object.keys(withoutLane.toolCalls).join(" -> ")}
                    </p>
                  </div>

                  <ul className="flex flex-col gap-2.5 border-t border-rule pt-4 text-sm leading-relaxed text-ink-1">
                    {(withoutLane.bullets.length > 0
                      ? withoutLane.bullets
                      : [withoutLane.rawText.slice(0, 260)]
                    ).map((b, i) => (
                      <li key={i} className="flex gap-2.5">
                        <span className="font-mono text-xs text-negative tabular-nums">
                          [!]
                        </span>
                        <span>{b}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          </div>

          <footer className="border-t border-rule px-6 py-3 text-xs text-ink-2">
             Trap exposure: <span className="font-mono">legacy_vip_flag</span> (2023 promo) &{" "}
            <span className="font-mono">ord_stat_cd = 99</span> (QA load-test rows)
          </footer>
        </article>

        {/* EXHIBIT B — POWERED BY KNOWLEDGE STUDIO */}
        <article
          aria-label="Exhibit B: Powered by Knowledge Studio"
          className="flex flex-col justify-between rounded-ui border border-rule border-t-[3px] border-t-accent bg-surface-1"
        >
          <div>
            <header className="flex items-baseline justify-between gap-2 border-b border-rule bg-surface-2 px-6 py-3.5">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-accent">
                  Exhibit B · Powered by Knowledge Studio
                </p>
                <h2 className="font-display text-lg font-semibold text-ink-1">
                  Governed Context Set via Managed MCP
                </h2>
              </div>
              <span className="font-mono text-xs text-accent">
                dataplex.googleapis.com/mcp
              </span>
            </header>

            <div className="p-6 sm:p-7">
              {withLane.status === "idle" ? (
                <div className="py-8">
                  <p className="text-sm leading-relaxed text-ink-2">
                    Consults Google Cloud Knowledge Studio over{" "}
                    <span className="font-mono text-ink-1">search_entries</span> and{" "}
                    <span className="font-mono text-ink-1">lookup_context</span> before writing
                    SQL, enforcing certified segmentation{" "}
                    <span className="font-mono text-accent">[§1]</span> and revenue{" "}
                    <span className="font-mono text-accent">[§2]</span> rules.
                  </p>
                </div>
              ) : null}

              {withLane.status === "running" ? (
                <div role="status" aria-live="polite" className="flex flex-col gap-3 py-8">
                  <p className="text-xs font-semibold uppercase tracking-[0.08em] text-accent">
                    In progress · {liveClockS.toFixed(1)}s
                  </p>
                  <p className="font-display text-xl text-ink-1">
                    {withLane.activeLabel}...
                  </p>
                  <ol className="flex flex-col gap-1.5 border-l border-accent pl-4 font-mono text-xs text-ink-2">
                    {withLane.steps.map((s, idx) => (
                      <li key={`${s.tool}-${idx}`} className="tabular-nums">
                        +{(s.elapsedMs / 1000).toFixed(1)}s · {s.tool}
                      </li>
                    ))}
                  </ol>
                </div>
              ) : null}

              {withLane.status === "error" ? (
                <ErrorState
                  title="Exhibit B failed"
                  description={withLane.errorMessage}
                />
              ) : null}

              {withLane.status === "done" ? (
                <div className="flex flex-col gap-5">
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-positive">
                      Certified benchmark · Policy governed
                    </p>
                    <p className="mt-1 font-display text-4xl font-semibold tracking-tight text-positive tabular-nums sm:text-[42px]">
                      {withLane.headlineDisplay ?? "Figure reported below"}
                    </p>
                    <p className="mt-1 font-mono text-xs text-ink-2 tabular-nums">
                      {(withLane.elapsedMs / 1000).toFixed(1)}s ·{" "}
                      {Object.keys(withLane.toolCalls).join(" -> ")}
                    </p>
                  </div>

                  <ul className="flex flex-col gap-2.5 border-t border-rule pt-4 text-sm leading-relaxed text-ink-1">
                    {(withLane.bullets.length > 0
                      ? withLane.bullets
                      : [withLane.rawText.slice(0, 260)]
                    ).map((b, i) => (
                      <li key={i} className="flex gap-2.5">
                        <span className="font-mono text-xs font-medium text-accent tabular-nums">
                          [§{i + 1}]
                        </span>
                        <span>{b}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          </div>

          <footer className="border-t border-rule px-6 py-3 text-xs text-ink-2">
            Citations: <span className="font-mono text-accent">[§1]</span>{" "}
            customer_segmentation_policy · <span className="font-mono text-accent">[§2]</span>{" "}
            governed_net_revenue_metric · <span className="font-mono text-accent">[§3]</span>{" "}
            order_status_and_qa_exclusion
          </footer>
        </article>
      </div>

      {/* Progressive Disclosure Drawer 1: Executed SQL Redline (Shown after query run, collapsed by default) */}
      {(withoutLane.status === "done" || withLane.status === "done") ? (
        <section className="rounded-ui border border-rule bg-surface-1">
          <button
            type="button"
            aria-expanded={showProof}
            onClick={() => setShowProof((v) => !v)}
            className={cn(
              "flex w-full items-center justify-between px-6 py-3.5 text-left text-sm font-medium text-ink-1",
              "bg-surface-2 transition-[background-color] duration-(--dur-fast) ease-out hover:bg-surface-0",
            )}
          >
            <span>
              Technical evidence — Side-by-side executed SQL redline & Knowledge Studio MCP trace
            </span>
            <span className="font-mono text-xs text-accent">
              {showProof ? "Hide SQL & trace" : "Inspect SQL & trace"}
            </span>
          </button>

          {showProof ? (
            <div className="grid grid-cols-1 gap-6 border-t border-rule p-6 transition-opacity duration-(--dur-base) ease-out lg:grid-cols-2">
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-negative">
                  Exhibit A — Ungrounded SQL Executed
                </p>
                <pre className="overflow-x-auto rounded-ui border border-rule bg-surface-0 p-4 font-mono text-xs leading-relaxed text-ink-1">
                  {withoutLane.sql || "-- SQL not captured"}
                </pre>
              </div>
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-positive">
                  Exhibit B — Knowledge Studio Governed SQL Executed
                </p>
                <pre className="overflow-x-auto rounded-ui border border-rule bg-surface-0 p-4 font-mono text-xs leading-relaxed text-ink-1">
                  {withLane.sql || "-- SQL not captured"}
                </pre>
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      {/* Progressive Disclosure Drawer 2: Agent Code Sample Comparison (Always available, collapsed by default) */}
      <section className="rounded-ui border border-rule bg-surface-1">
        <button
          type="button"
          aria-expanded={showCodeSample}
          onClick={() => setShowCodeSample((v) => !v)}
          className={cn(
            "flex w-full items-center justify-between px-6 py-3.5 text-left text-sm font-medium text-ink-1",
            "bg-surface-2 transition-[background-color] duration-(--dur-fast) ease-out hover:bg-surface-0",
          )}
        >
          <span>
            Technical evidence — Side-by-side agent code sample (Without MCP context vs. With Knowledge Studio MCP)
          </span>
          <span className="font-mono text-xs text-accent">
            {showCodeSample ? "Hide code comparison" : "Inspect code comparison"}
          </span>
        </button>

        {showCodeSample ? (
          <div className="grid grid-cols-1 gap-6 border-t border-rule p-6 transition-opacity duration-(--dur-base) ease-out lg:grid-cols-2">
            <div>
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-xs font-semibold uppercase tracking-[0.08em] text-ink-2">
                  Exhibit A — Without MCP Knowledge Context
                </p>
                <span className="font-mono text-xs text-ink-2">
                  agent_1_without_kc · 2 BigQuery tools only
                </span>
              </div>
              <pre className="overflow-x-auto rounded-ui border border-rule bg-surface-0 p-4 font-mono text-xs leading-relaxed text-ink-1">
                {AGENT_WITHOUT_MCP_CODE}
              </pre>
            </div>
            <div>
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-xs font-semibold uppercase tracking-[0.08em] text-accent">
                  Exhibit B — Powered by Knowledge Studio MCP
                </p>
                <span className="font-mono text-xs text-accent">
                  agent_2_with_kc · + McpToolset(dataplex.googleapis.com/mcp)
                </span>
              </div>
              <pre className="overflow-x-auto rounded-ui border border-accent bg-surface-0 p-4 font-mono text-xs leading-relaxed text-ink-1">
                {AGENT_WITH_MCP_CODE}
              </pre>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}
