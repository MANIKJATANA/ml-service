"use client";

import { ChevronLeft, ChevronRight, ScrollText } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { RoleGate } from "@/components/role-gate";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ROLE_LABELS } from "@/lib/auth/routes";
import { useDownloadLog } from "@/lib/hooks/use-audit";
import { formatDateTime } from "@/lib/utils";

const PAGE_SIZE = 50;

export default function AuditLogPage() {
  // school_admin only (a teacher in the (school) group is redirected home — the backend
  // also 403s `audit:view`); the fetch below never fires for a disallowed role.
  return (
    <RoleGate allow={["school_admin"]}>
      <AuditLog />
    </RoleGate>
  );
}

function AuditLog() {
  const [offset, setOffset] = useState(0);
  const { page, error, isLoading, mutate } = useDownloadLog({
    limit: PAGE_SIZE,
    offset,
  });

  const items = page?.items ?? [];
  const total = page?.total ?? 0;
  const start = total === 0 ? 0 : offset + 1;
  const end = offset + items.length;
  const canPrev = offset > 0;
  const canNext = end < total;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Access log"
        description="Every photo download in your school — who, what, and when (newest first)."
      />

      {isLoading && !page ? (
        <Card className="flex flex-col gap-2 p-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </Card>
      ) : null}

      {error ? (
        <EmptyState
          role="alert"
          title="Couldn't load the access log"
          description="Something went wrong reaching the server."
          action={
            <Button variant="secondary" onClick={() => mutate()}>
              Retry
            </Button>
          }
        />
      ) : null}

      {page && !error ? (
        total === 0 ? (
          <EmptyState
            icon={<ScrollText className="size-6" aria-hidden="true" />}
            title="No downloads yet"
            description="Downloads will appear here as staff and students save photos."
          />
        ) : (
          <div className="flex flex-col gap-4">
            <Card className="overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>When</TableHead>
                    <TableHead>Who</TableHead>
                    <TableHead>Photo</TableHead>
                    <TableHead>Downloaded as</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((row) => (
                    <TableRow key={row.id} className="hover:bg-surface">
                      <TableCell className="whitespace-nowrap text-ink-secondary">
                        <time dateTime={row.downloaded_at}>
                          {formatDateTime(row.downloaded_at)}
                        </time>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="text-ink">
                            {row.actor_email ?? "Removed account"}
                          </span>
                          <span className="text-body-sm text-ink-muted">
                            {ROLE_LABELS[row.actor_role]}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Link
                          href={`/photos/${row.media_id}`}
                          className="text-accent-hover hover:underline"
                        >
                          {row.event_name ?? "View photo"}
                        </Link>
                      </TableCell>
                      <TableCell className="text-ink-secondary">
                        {row.subject_student_name ?? "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>

            <div className="flex items-center justify-between gap-4">
              <p className="text-body-sm text-ink-muted" aria-live="polite">
                Showing {start}–{end} of {total}
              </p>
              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                  disabled={!canPrev}
                >
                  <ChevronLeft className="size-4" aria-hidden="true" />
                  Previous
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => setOffset((o) => o + PAGE_SIZE)}
                  disabled={!canNext}
                >
                  Next
                  <ChevronRight className="size-4" aria-hidden="true" />
                </Button>
              </div>
            </div>
          </div>
        )
      ) : null}
    </div>
  );
}
