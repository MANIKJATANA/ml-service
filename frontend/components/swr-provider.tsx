"use client";

import type { ReactNode } from "react";
import { SWRConfig } from "swr";

/**
 * App-wide SWR defaults (decisions/0032): no auto-retry (each screen has an
 * explicit Retry button — the single retry path, so error states stay stable) and
 * no revalidate-on-focus.
 */
export function SwrProvider({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ shouldRetryOnError: false, revalidateOnFocus: false }}>
      {children}
    </SWRConfig>
  );
}
