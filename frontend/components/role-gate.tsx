"use client";

import { useRouter } from "next/navigation";
import { type ReactNode, useEffect } from "react";

import { FullPageSpinner } from "@/components/ui/spinner";
import type { Role } from "@/lib/api/types";
import { homePathForRole } from "@/lib/auth/routes";
import { useMe } from "@/lib/hooks/use-me";

/**
 * Role gate for a single screen inside an already-AuthGuarded route group — e.g. a
 * school-admin-only page in the (school) group, which admits both school_admin and
 * teacher. The parent AuthGuard has already resolved the session and rendered the
 * shell, so this only redirects a disallowed role to its home. It renders no shell
 * and no spinner: by the time a child renders, the user is in the SWR cache, so a
 * disallowed role never sees the guarded screen (and its data fetch never fires).
 */
export function RoleGate({ allow, children }: { allow: Role[]; children: ReactNode }) {
  const router = useRouter();
  const { user } = useMe();
  const denied = user ? !allow.includes(user.role) : false;

  useEffect(() => {
    if (user && denied) router.replace(homePathForRole(user.role));
  }, [user, denied, router]);

  if (!user || denied) return <FullPageSpinner />;
  return <>{children}</>;
}
