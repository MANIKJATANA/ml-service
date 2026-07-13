"use client";

import { Button } from "@/components/ui/button";
import { FullPageMessage } from "@/components/ui/full-page-message";

/** Full-viewport error state with a retry — used when the session can't be resolved for a
 *  non-auth reason (e.g. the backend is unreachable), so we don't wrongly log out. */
export function FullPageError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <FullPageMessage
      title="Something went wrong"
      description={message}
      action={
        <Button variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      }
    />
  );
}
