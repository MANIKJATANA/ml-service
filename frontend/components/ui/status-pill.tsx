import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const pillVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-body-sm font-medium",
  {
    variants: {
      tone: {
        neutral: "bg-surface-2 text-ink-secondary",
        success: "bg-success-soft text-success-strong",
        warning: "bg-warning-soft text-warning-strong",
        error: "bg-error-soft text-error-strong",
        info: "bg-info-soft text-info-strong",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface StatusPillProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof pillVariants> {
  /** Show a leading dot in the tone color. */
  dot?: boolean;
}

/** Pale-tint status pill (maps enrollment/processing/needs_review to a semantic tone). */
export function StatusPill({ className, tone, dot = false, children, ...props }: StatusPillProps) {
  return (
    <span className={cn(pillVariants({ tone }), className)} {...props}>
      {dot ? <span className="size-1.5 rounded-full bg-current" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}
