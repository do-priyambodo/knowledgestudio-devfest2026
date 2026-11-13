import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Button primitive (shadcn-style), tokens only.
 * Press feedback is a 1px translate over --dur-fast (80ms); reduced motion
 * disables it. Transitions name their properties (never `all`).
 */
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "outline" | "ghost";
}

const VARIANTS: Record<NonNullable<ButtonProps["variant"]>, string> = {
  primary: "bg-ink-1 text-surface-1 hover:bg-ink-2",
  secondary: "border border-rule bg-surface-2 text-ink-1 hover:bg-surface-1",
  outline: "border border-rule bg-transparent text-ink-1 hover:bg-surface-2",
  ghost: "bg-transparent text-ink-2 hover:bg-surface-2 hover:text-ink-1",
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", type = "button", ...props }, ref) => {
    return (
      <button
        ref={ref}
        type={type}
        className={cn(
          "inline-flex items-center justify-center gap-2 rounded-ui px-3 py-1.5 text-sm font-medium",
          "transition-[background-color,color,border-color,transform] duration-(--dur-fast) ease-out",
          "active:translate-y-px motion-reduce:transition-none motion-reduce:active:translate-y-0",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring",
          "disabled:pointer-events-none disabled:opacity-50",
          VARIANTS[variant],
          className,
        )}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";
