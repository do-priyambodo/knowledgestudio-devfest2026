import { cn } from "@/lib/utils";

/**
 * Designed empty / loading / error states (RULES-UX §2.1 item 5).
 * Tokens only. Each app restyles these once its DESIGN.md is approved; the
 * semantics (roles, live regions, copy that says what to do next) stay.
 */

interface StateProps {
  title: string;
  description?: string;
  /** Optional call to action, e.g. a <Button>. */
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({ title, description, action, className }: StateProps) {
  return (
    <section
      className={cn(
        "flex flex-col items-start gap-2 rounded-ui border border-dashed border-rule bg-surface-1 px-5 py-6",
        className,
      )}
    >
      <h2 className="text-base font-medium text-ink-1">{title}</h2>
      {description ? <p className="text-sm text-ink-2">{description}</p> : null}
      {action ? <div className="pt-2">{action}</div> : null}
    </section>
  );
}

export function LoadingState({
  label,
  rows = 3,
  className,
}: {
  /** Announced to assistive tech, e.g. "Loading records". */
  label: string;
  rows?: number;
  className?: string;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      className={cn("flex flex-col gap-2 rounded-ui border border-rule bg-surface-1 px-5 py-4", className)}
    >
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, index) => (
        <div
          key={index}
          aria-hidden="true"
          className="h-3 rounded-ui bg-surface-2 motion-safe:animate-pulse"
          style={{ width: `${90 - index * 15}%` }}
        />
      ))}
    </div>
  );
}

export function ErrorState({ title, description, action, className }: StateProps) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-start gap-1 rounded-ui border border-rule border-l-2 border-l-negative bg-surface-1 px-5 py-4",
        className,
      )}
    >
      <p className="text-sm font-medium text-negative">{title}</p>
      {description ? <p className="text-sm text-ink-2">{description}</p> : null}
      {action ? <div className="pt-2">{action}</div> : null}
    </div>
  );
}
