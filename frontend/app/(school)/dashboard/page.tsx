"use client";

import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { ROLE_LABELS } from "@/lib/auth/routes";
import { useMe } from "@/lib/hooks/use-me";

export default function DashboardPage() {
  const { user, isLoading } = useMe();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Dashboard" description="Welcome to your school workspace." />
      <Card className="p-6">
        {isLoading || !user ? (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-4 w-48" />
            <Skeleton className="h-4 w-32" />
          </div>
        ) : (
          <dl className="grid gap-6 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <dt className="text-body-sm text-ink-muted">Signed in as</dt>
              <dd className="text-body text-ink">{user.email}</dd>
            </div>
            <div className="flex flex-col gap-1">
              <dt className="text-body-sm text-ink-muted">Role</dt>
              <dd>
                <StatusPill tone="info">{ROLE_LABELS[user.role]}</StatusPill>
              </dd>
            </div>
          </dl>
        )}
      </Card>
      <p className="text-body-sm text-ink-muted">
        Staff, students, events, and galleries arrive in the next phases.
      </p>
    </div>
  );
}
