"use client";

import { useSyncExternalStore } from "react";
import { cn } from "@/lib/utils";

export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "theme";
const DARK_CLASS = "theme-dark";

function readTheme(): Theme {
  return document.documentElement.classList.contains(DARK_CLASS) ? "dark" : "light";
}

function subscribe(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
}

function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle(DARK_CLASS, theme === "dark");
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch (error) {
    console.warn("Theme preference could not be saved", error);
  }
}

const OPTIONS: readonly { value: Theme; label: string }[] = [
  { value: "light", label: "Paper" },
  { value: "dark", label: "Espresso" },
];

export function ThemeToggle({ className }: { className?: string }) {
  const theme = useSyncExternalStore(subscribe, readTheme, () => "light" as Theme);

  return (
    <div
      role="group"
      aria-label="Folio theme"
      className={cn("inline-flex rounded-ui border border-rule bg-surface-1 p-0.5", className)}
    >
      {OPTIONS.map((option) => {
        const pressed = theme === option.value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={pressed}
            onClick={() => applyTheme(option.value)}
            className={cn(
              "rounded-ui px-2.5 py-1 text-xs font-medium tracking-wide",
              "transition-[background-color,color] duration-(--dur-fast) ease-out",
              pressed ? "bg-ink-1 text-surface-1" : "text-ink-2 hover:text-ink-1",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
