"use client";

import { ArenaExhibit } from "@/components/arena-exhibit";
import { ThemeToggle } from "@/components/theme-toggle";

export default function FolioHomePage() {
  return (
    <div className="min-h-dvh bg-surface-0 text-ink-1">
      <main className="mx-auto max-w-[1280px] px-6 py-8 sm:px-10 lg:px-14">
        <header className="mb-7 border-t-[3px] border-b border-ink-1 py-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-accent">
              Cymbal Retail Malaysia · GDG DevFest Kuala Lumpur 2026 - LIVE DEMO!
            </p>
            <div className="flex items-center gap-4">
              <span className="hidden font-mono text-xs text-ink-2 sm:inline">
                cymbal_retail_my
              </span>
              <ThemeToggle />
            </div>
          </div>
          <h1 className="mt-2 font-display text-2xl font-semibold tracking-tight text-ink-1 sm:text-[30px]">
            Same question, same model, different data context, different result
          </h1>
        </header>

        <ArenaExhibit />

        <footer className="mt-10 flex flex-wrap items-center justify-between gap-2 border-t border-rule pt-4 text-xs text-ink-2">
          <span>Google Cloud Knowledge Studio · BigQuery · Google ADK</span>
          <span className="font-mono tabular-nums">Read-only SQL guard · 1.00 GiB query cap</span>
        </footer>
      </main>
    </div>
  );
}
