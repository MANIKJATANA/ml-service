"use client";

import { useRouter } from "next/navigation";
import { type ReactNode, useEffect } from "react";

import { AppShell } from "@/components/ui/app-shell";
import { FullPageError } from "@/components/ui/full-page-error";
import { FullPageSpinner } from "@/components/ui/spinner";
import { isApiError } from "@/lib/api/errors";
import type { Role } from "@/lib/api/types";
import { homePathForRole } from "@/lib/auth/routes";
import { useMe } from "@/lib/hooks/use-me";

/**
 * Client auth boundary for a route group. `proxy.ts` already ensured a session
 * cookie is present; this resolves the real user and enforces role + must-change
 * (redirecting as needed), then renders the shell (decisions/0031).
 *
 * A 401 means the session is truly dead → /login. Any other error (backend 5xx /
 * network) is NOT a logout — we show a retry rather than bounce to /login (which
 * proxy.ts would bounce back to /, looping while the backend is down).
 */
export function AuthGuard({ allow, children }: { allow: Role[]; children: ReactNode }) {
  const router = useRouter();
  const { user, isLoading, error, mutate } = useMe();

  const sessionDead = isApiError(error) && error.status === 401;
  const backendError = Boolean(error) && !sessionDead;

  let redirectTo: string | null = null;
  if (!isLoading && !backendError) {
    // BP18a: a mid-session 401 (session truly dead) carries a reason so login can say "you
    // were signed out"; a plain not-signed-in has none.
    if (sessionDead) redirectTo = "/login?reason=expired";
    else if (!user) redirectTo = "/login";
    else if (user.must_change_password) redirectTo = "/change-password";
    else if (!allow.includes(user.role)) redirectTo = homePathForRole(user.role);
  }

  useEffect(() => {
    if (redirectTo) router.replace(redirectTo);
  }, [redirectTo, router]);

  if (backendError) {
    return <FullPageError message="Couldn't reach the server." onRetry={() => void mutate()} />;
  }
  if (isLoading || redirectTo || !user) {
    return <FullPageSpinner />;
  }
  return <AppShell user={user}>{children}</AppShell>;
}
