"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { FullPageMessage } from "@/components/ui/full-page-message";

/**
 * Segment error boundary — catches render errors below the root layout and offers a reset.
 * Full-page (it renders outside the app shell). We deliberately use `reset` (re-render), not
 * 16.2's `unstable_retry` (re-fetch): this app's data errors are handled in-component via SWR
 * + Retry, so a boundary hit is a render fault where a plain re-render is the right recovery —
 * and we avoid depending on an `unstable_`-prefixed API.
 */
export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // React already surfaces this in dev; a real deployment would forward it to a logger.
    console.error(error);
  }, [error]);

  return (
    <FullPageMessage
      title="Something went wrong"
      description="An unexpected error occurred. Please try again."
      action={
        <Button variant="secondary" onClick={() => reset()}>
          Try again
        </Button>
      }
    />
  );
}
