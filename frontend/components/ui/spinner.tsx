import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

/** Inline loading spinner (defaults to 1rem; size via className). */
export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("size-4 animate-spin", className)} aria-hidden="true" />;
}

/** Centered full-viewport spinner for route-level loading / redirect states. */
export function FullPageSpinner() {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-surface" role="status" aria-label="Loading">
      <Spinner className="size-6 text-ink-muted" />
    </div>
  );
}
