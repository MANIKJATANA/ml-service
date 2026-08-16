"use client";

import type { ReactNode } from "react";
import { mutate, SWRConfig } from "swr";

import { isApiError } from "@/lib/api/errors";

/** The `useMe` SWR key — revalidating it drives the AuthGuard's redirect. */
const ME_KEY = "auth/me";

/**
 * App-wide SWR defaults (decisions/0032): no auto-retry (each screen has an
 * explicit Retry button — the single retry path, so error states stay stable) and
 * no revalidate-on-focus.
 *
 * BP21b (decisions/0074): a shared 401 interceptor. If a mid-session 401 hits ANY
 * data key (the session expired and the BFF cleared the cookies), revalidate the
 * user so the AuthGuard bounces to /login?reason=expired — instead of the page
 * showing "Something went wrong" over a Retry that can never succeed. The `auth/me`
 * key is skipped (the AuthGuard handles its own 401 directly) so this can't loop.
 */
export function SwrProvider({ children }: { children: ReactNode }) {
  return (
    <SWRConfig
      value={{
        shouldRetryOnError: false,
        revalidateOnFocus: false,
        onError: (error, key) => {
          if (isApiError(error) && error.status === 401 && key !== ME_KEY) {
            void mutate(ME_KEY);
          }
        },
      }}
    >
      {children}
    </SWRConfig>
  );
}
