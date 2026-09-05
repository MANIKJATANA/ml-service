"use client";

import { AlertTriangle, ChevronDown, ChevronUp, MessageCircle, MoonStar } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

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
import { formatDate } from "@/lib/utils";

// BP23: the estate list is fully materialized (unpaginated), so the funnel sorts client-side.
type SortKey =
  | "school_name"
  | "teachers"
  | "students"
  | "enrolled"
  | "events"
  | "distributed"
  | "signed_in_students"
  | "whatsapp_sent_month"
  | "whatsapp_sent"
  | "days_to_first_delivery"
  | "stalled_since";

// A comparable value per sortable column (nulls pushed to the end on ASC).
const ACCESSOR: Record<SortKey, (f: SchoolFunnelResponse) => number | string> = {
  school_name: (f) => f.school_name.toLowerCase(),
  teachers: (f) => f.teachers,
  students: (f) => f.students,
  enrolled: (f) => f.enrolled,
  events: (f) => f.events,
  distributed: (f) => f.distributed,
  signed_in_students: (f) => f.signed_in_students,
  whatsapp_sent_month: (f) => f.whatsapp_sent_month,
  whatsapp_sent: (f) => f.whatsapp_sent,
  days_to_first_delivery: (f) =>
    f.days_to_first_delivery ?? Number.POSITIVE_INFINITY,
  stalled_since: (f) => f.stalled_since ?? "", // "" (never) sorts before any ISO date
};

export default function EstateAnalyticsPage() {
  const { estate, error, isLoading, mutate } = useEstateAnalytics();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Estate health"
        description="How each school is adopting — the funnel from students to announced photos, and who's stalled."
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

/** A click-to-sort funnel header (BP23) — toggles direction on the active column. */
function SortHead({
  label,
  k,
  sortKey,
  dir,
  onSort,
  numeric,
}: {
  label: string;
  k: SortKey;
  sortKey: SortKey;
  dir: "asc" | "desc";
  onSort: (k: SortKey) => void;
  numeric?: boolean;
}) {
  const active = sortKey === k;
  return (
    <TableHead
      className={numeric ? "text-right" : undefined}
      aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        onClick={() => onSort(k)}
        aria-label={`Sort by ${label}${active ? (dir === "asc" ? ", ascending" : ", descending") : ""}`}
        className={`inline-flex items-center gap-1 rounded-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
          active ? "text-ink" : "hover:text-ink"
        } ${numeric ? "flex-row-reverse" : ""}`}
      >
        {label}
        {active ? (
          dir === "asc" ? (
            <ChevronUp className="size-3.5" aria-hidden="true" />
          ) : (
            <ChevronDown className="size-3.5" aria-hidden="true" />
          )
        ) : null}
      </button>
    </TableHead>
  );
}

function EstateBody({ e }: { e: EstateAnalyticsResponse }) {
  const needsAttention = e.schools.filter((s) => s.stalled || s.idle);
  const [sortKey, setSortKey] = useState<SortKey>("school_name");
  const [dir, setDir] = useState<"asc" | "desc">("asc");

  function onSort(k: SortKey) {
    if (k === sortKey) {
      setDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(k);
      // Text default A→Z; numeric/date columns default to most-interesting-first (desc).
      setDir(k === "school_name" ? "asc" : "desc");
    }
  }

  const get = ACCESSOR[sortKey];
  const sorted = [...e.schools].sort((a, b) => {
    const va = get(a);
    const vb = get(b);
    let cmp: number;
    if (typeof va === "number" && typeof vb === "number") cmp = va - vb;
    else cmp = String(va).localeCompare(String(vb));
    if (cmp === 0) cmp = a.school_name.localeCompare(b.school_name); // stable tiebreak
    return dir === "asc" ? cmp : -cmp;
  });

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
                className="ml-auto shrink-0 rounded text-body-sm font-medium text-accent hover:text-accent-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                View school →
              </Link>
            </div>
          ))}
        </Card>
      ) : (
        <p className="text-body-sm text-ink-secondary">Every school is on track — nothing stalled.</p>
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

      {/* WhatsApp cost across the estate — each image sent is one message (the cost unit). This
          month is the current bill; the total is lifetime. Per-school numbers are in the funnel. */}
      <Card className="flex flex-wrap items-center justify-between gap-4 p-5">
        <div className="flex items-center gap-2">
          <MessageCircle className="size-5 shrink-0 text-ink-secondary" aria-hidden="true" />
          <div className="flex flex-col">
            <h2 className="text-headline text-ink">WhatsApp images sent</h2>
            <p className="text-body-sm text-ink-secondary">
              Each image sent is one message — the cost unit.
            </p>
          </div>
        </div>
        <div className="flex gap-8">
          <div className="flex flex-col">
            <span className="text-body-sm text-ink-secondary">This month</span>
            <span className="text-headline tabular-nums text-ink">
              {e.whatsapp_sent_month_total.toLocaleString()}
            </span>
          </div>
          <div className="flex flex-col">
            <span className="text-body-sm text-ink-secondary">All time</span>
            <span className="text-headline tabular-nums text-ink">
              {e.whatsapp_sent_total.toLocaleString()}
            </span>
          </div>
        </div>
      </Card>

      {/* Funnel */}
      <section className="flex flex-col gap-3">
        <h2 className="text-headline text-ink">Adoption funnel</h2>
        {e.schools.length === 0 ? (
          <EmptyState title="No schools yet" description="Onboard a school to see its adoption." />
        ) : (
          <Card className="overflow-x-auto">
            <Table className="min-w-[980px]">
              <TableHeader>
                <TableRow>
                  <SortHead label="School" k="school_name" sortKey={sortKey} dir={dir} onSort={onSort} />
                  <SortHead label="Staff" k="teachers" sortKey={sortKey} dir={dir} onSort={onSort} numeric />
                  <SortHead label="Students" k="students" sortKey={sortKey} dir={dir} onSort={onSort} numeric />
                  <SortHead label="Enrolled" k="enrolled" sortKey={sortKey} dir={dir} onSort={onSort} numeric />
                  <SortHead label="Events" k="events" sortKey={sortKey} dir={dir} onSort={onSort} numeric />
                  <SortHead label="Announced" k="distributed" sortKey={sortKey} dir={dir} onSort={onSort} numeric />
                  <SortHead label="Signed in" k="signed_in_students" sortKey={sortKey} dir={dir} onSort={onSort} numeric />
                  <SortHead label="WhatsApp (mo)" k="whatsapp_sent_month" sortKey={sortKey} dir={dir} onSort={onSort} numeric />
                  <SortHead label="WhatsApp (all)" k="whatsapp_sent" sortKey={sortKey} dir={dir} onSort={onSort} numeric />
                  <SortHead label="Days to deliver" k="days_to_first_delivery" sortKey={sortKey} dir={dir} onSort={onSort} numeric />
                  <SortHead label="Last event" k="stalled_since" sortKey={sortKey} dir={dir} onSort={onSort} numeric />
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sorted.map((f) => {
                  const status = statusOf(f);
                  return (
                    <TableRow key={f.school_id}>
                      <TableCell>
                        <Link
                          href={`/schools/${f.school_id}`}
                          className="rounded font-medium text-ink hover:text-accent-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          {f.school_name}
                        </Link>
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-ink-secondary">{f.teachers}</TableCell>
                      <TableCell className="text-right tabular-nums text-ink-secondary">
                        {f.students.toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-ink-secondary">
                        {f.enrolled.toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-ink-secondary">{f.events}</TableCell>
                      <TableCell className="text-right tabular-nums text-ink-secondary">{f.distributed}</TableCell>
                      <TableCell className="text-right tabular-nums text-ink-secondary">
                        {f.signed_in_students.toLocaleString()}
                      </TableCell>
                      {/* WhatsApp cost: images sent this month (the current bill) + all-time. */}
                      <TableCell className="text-right tabular-nums text-ink-secondary">
                        {f.whatsapp_sent_month.toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-ink-secondary">
                        {f.whatsapp_sent.toLocaleString()}
                      </TableCell>
                      {/* BP23 age axis: days from signup to first announce; most-recent event. */}
                      <TableCell className="text-right tabular-nums text-ink-secondary">
                        {f.days_to_first_delivery ?? "—"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-ink-secondary">
                        {f.stalled_since ? formatDate(f.stalled_since) : "—"}
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
