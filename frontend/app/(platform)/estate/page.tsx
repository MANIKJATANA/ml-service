"use client";

import { AlertTriangle, MoonStar } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { StatCard } from "@/components/ui/stat-card";
import { StatusPill } from "@/components/ui/status-pill";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { EstateAnalyticsResponse, SchoolFunnelResponse } from "@/lib/api/types";
import { useEstateAnalytics } from "@/lib/hooks/use-estate-analytics";

export default function EstateAnalyticsPage() {
  const { estate, error, isLoading, mutate } = useEstateAnalytics();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Estate health"
        description="How each school is adopting — the funnel from students to delivered photos, and who's stalled."
      />
      {isLoading && !estate ? (
        <EstateSkeleton />
      ) : error || !estate ? (
        <EmptyState
          role="alert"
          title="Couldn't load estate analytics"
          description="Something went wrong reaching the server."
          action={
            <Button variant="secondary" onClick={() => void mutate()}>
              Try again
            </Button>
          }
        />
      ) : (
        <EstateBody e={estate} />
      )}
    </div>
  );
}

function statusOf(f: SchoolFunnelResponse): { tone: "success" | "warning" | "error"; label: string } {
  if (f.stalled) return { tone: "error", label: "Stalled" };
  if (f.idle) return { tone: "warning", label: "Idle" };
  return { tone: "success", label: "Healthy" };
}

function EstateBody({ e }: { e: EstateAnalyticsResponse }) {
  const needsAttention = e.schools.filter((s) => s.stalled || s.idle);
  return (
    <div className="flex flex-col gap-6">
      {/* Alerts */}
      {needsAttention.length > 0 ? (
        <Card className="divide-y divide-hairline">
          {needsAttention.map((f) => (
            <div key={f.school_id} className="flex flex-wrap items-center gap-4 p-4">
              <span className={f.stalled ? "shrink-0 text-error" : "shrink-0 text-warning-strong"}>
                {f.stalled ? (
                  <AlertTriangle className="size-4" aria-hidden="true" />
                ) : (
                  <MoonStar className="size-4" aria-hidden="true" />
                )}
              </span>
              <div className="flex min-w-0 flex-col">
                <span className="text-body font-medium text-ink">{f.school_name}</span>
                <span className="text-body-sm text-ink-secondary">
                  {f.stalled
                    ? `${f.students.toLocaleString()} students imported, none enrolled — not switched on yet.`
                    : "Enrolled, but no event created in the last 30 days."}
                </span>
              </div>
              <Link
                href={`/schools/${f.school_id}`}
                className="ml-auto shrink-0 text-body-sm font-medium text-accent hover:text-accent-hover"
              >
                View school →
              </Link>
            </div>
          ))}
        </Card>
      ) : (
        <p className="text-body-sm text-ink-muted">Every school is on track — nothing stalled.</p>
      )}

      {/* Totals */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Schools"
          value={e.total_schools.toLocaleString()}
          hint={`${e.stalled_schools.toLocaleString()} stalled`}
        />
        <StatCard
          label="Students"
          value={e.total_students.toLocaleString()}
          hint={`${e.total_enrolled.toLocaleString()} enrolled`}
        />
        <StatCard label="Enrolled" value={e.total_enrolled.toLocaleString()} />
        <StatCard label="Events" value={e.total_events.toLocaleString()} />
      </div>

      {/* Funnel */}
      <section className="flex flex-col gap-3">
        <h2 className="text-headline text-ink">Adoption funnel</h2>
        {e.schools.length === 0 ? (
          <EmptyState title="No schools yet" description="Onboard a school to see its adoption." />
        ) : (
          <Card className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>School</TableHead>
                  <TableHead>Staff</TableHead>
                  <TableHead>Students</TableHead>
                  <TableHead>Enrolled</TableHead>
                  <TableHead>Events</TableHead>
                  <TableHead>Distributed</TableHead>
                  <TableHead>Signed in</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {e.schools.map((f) => {
                  const status = statusOf(f);
                  return (
                    <TableRow key={f.school_id}>
                      <TableCell>
                        <Link
                          href={`/schools/${f.school_id}`}
                          className="font-medium text-ink hover:text-accent-hover"
                        >
                          {f.school_name}
                        </Link>
                      </TableCell>
                      <TableCell className="tabular-nums text-ink-secondary">{f.teachers}</TableCell>
                      <TableCell className="tabular-nums text-ink-secondary">
                        {f.students.toLocaleString()}
                      </TableCell>
                      <TableCell className="tabular-nums text-ink-secondary">
                        {f.enrolled.toLocaleString()}
                      </TableCell>
                      <TableCell className="tabular-nums text-ink-secondary">{f.events}</TableCell>
                      <TableCell className="tabular-nums text-ink-secondary">{f.distributed}</TableCell>
                      <TableCell className="tabular-nums text-ink-secondary">
                        {f.signed_in_students.toLocaleString()}
                      </TableCell>
                      <TableCell>
                        <StatusPill tone={status.tone} dot>
                          {status.label}
                        </StatusPill>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </Card>
        )}
      </section>
    </div>
  );
}

function EstateSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {[0, 1, 2, 3].map((i) => (
        <Card key={i} className="flex flex-col gap-3 p-5">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-8 w-12" />
          <Skeleton className="h-3 w-24" />
        </Card>
      ))}
    </div>
  );
}
