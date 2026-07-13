import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
  /** Set "alert" on error states so screen readers announce the failure on mount (0037). */
  role?: "status" | "alert";
}

/** Centered "nothing here yet" state with an optional icon and call-to-action. */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
  role,
}: EmptyStateProps) {
  return (
    <div
      role={role}
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-card border border-dashed border-hairline bg-surface px-6 py-12 text-center",
        className,
      )}
    >
      {icon ? <div className="text-ink-muted">{icon}</div> : null}
      <div className="flex flex-col gap-1">
        <p className="text-headline text-ink">{title}</p>
        {description ? <p className="text-body text-ink-secondary">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}
