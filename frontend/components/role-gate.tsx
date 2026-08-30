"use client";

import Link from "next/link";
import { type ReactNode } from "react";

import { buttonVariants } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { FullPageSpinner } from "@/components/ui/spinner";
import type { Role } from "@/lib/api/types";
import { homePathForRole } from "@/lib/auth/routes";
import { useMe } from "@/lib/hooks/use-me";

/**
 * Role gate for a single screen inside an already-AuthGuarded route group — e.g. a
 * school-admin-only page in the (school) group, which admits both school_admin and
 * teacher. The parent AuthGuard has already resolved the session and rendered the
 * shell, so this only handles a disallowed role. It renders no shell: by the time a
 * child renders, the user is in the SWR cache, so a disallowed role never sees the
 * guarded screen (and its data fetch never fires).
 *
 * BP29 (R4-T07): a denied role now sees a brief "not available" message with a link to
 * its own home, instead of a silent forced redirect (which looked like a broken bounce).
 */
export function RoleGate({ allow, children }: { allow: Role[]; children: ReactNode }) {
  const { user } = useMe();

  if (!user) return <FullPageSpinner />;
  if (!allow.includes(user.role)) {
    return (
      <EmptyState
        role="status"
        title="Not available for your role"
        description="This page isn't part of your workspace. Head back to your dashboard to keep going."
        action={
          <Link
            href={homePathForRole(user.role)}
            className={buttonVariants({ variant: "secondary" })}
          >
            Go to dashboard
          </Link>
        }
      />
    );
  }
  return <>{children}</>;
}
