"use client";

import { Button } from "@/components/ui/button";

/** Full-viewport error state with a retry — used when the session can't be resolved
 *  for a non-auth reason (e.g. the backend is unreachable), so we don't wrongly log out. */
export function FullPageError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-surface px-4 text-center">
      <div className="flex flex-col gap-1">
        <p className="text-headline text-ink">Something went wrong</p>
        <p className="text-body text-ink-secondary">{message}</p>
      </div>
      <Button variant="secondary" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}
