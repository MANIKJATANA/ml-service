"use client";

import {
  AlertTriangle,
  ArrowRight,
  CalendarDays,
  CheckCircle2,
  Circle,
  GraduationCap,
  Loader2,
  ScanSearch,
  Send,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { ProgramAnalytics } from "@/components/analytics/program-analytics";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { StatCard } from "@/components/ui/stat-card";
import type { DashboardResponse } from "@/lib/api/types";
import { useDashboard } from "@/lib/hooks/use-dashboard";
import { cn } from "@/lib/utils";

type Tone = "error" | "warning" | "info";

interface DashAlert {
  key: string;
  tone: Tone;
  icon: ReactNode;
  title: string;
  description: string;
  href: string;
  cta: string;
}

const ALERT_ICON_TONE: Record<Tone, string> = {
  error: "text-error",
  warning: "text-warning-strong",
  info: "text-info-strong",
};

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** The needs-attention + live-status signals, in priority order — only the non-zero ones. */
function buildAlerts(d: DashboardResponse): DashAlert[] {
  const alerts: DashAlert[] = [];
  const { events_undistributed, enrollment_failures, needs_review, photos_failed } =
    d.needs_attention;
  if (events_undistributed > 0) {
    alerts.push({
      key: "undistributed",
      tone: "warning",
      icon: <Send className="size-4" aria-hidden="true" />,
      // BP19c: the predicate now catches a "second batch" too (new photos on an already-
      // distributed event), so the copy must be true for both — "to match", not "not sent".
      title: `${plural(events_undistributed, "event", "events")} with photos to match`,
      description: "Photos are uploaded but haven't been matched to students yet.",
      href: "/events",
      cta: "Review events",
    });
  }
  if (enrollment_failures > 0) {
    alerts.push({
      key: "failures",
      tone: "error",
      icon: <AlertTriangle className="size-4" aria-hidden="true" />,
      title: `${plural(enrollment_failures, "enrollment", "enrollments")} failed`,
      description: "These students won't appear in any photos until re-enrolled.",
      href: "/students?status=failed", // BP23: deep-link straight to the failed students
      cta: "Fix enrollments",
    });
  }
  if (photos_failed > 0) {
    alerts.push({
      key: "photos-failed",
      tone: "error",
      icon: <AlertTriangle className="size-4" aria-hidden="true" />,
      title: `${plural(photos_failed, "photo", "photos")} couldn't be matched`,
      description: "Some photos couldn't be matched — open the event to retry them.",
      href: "/events",
      cta: "Review events",
    });
  }
  if (needs_review > 0) {
    alerts.push({
      key: "review",
      tone: "warning",
      icon: <ScanSearch className="size-4" aria-hidden="true" />,
      title: `${plural(needs_review, "match", "matches")} need review`,
      description: "Some matches were uncertain — open an event gallery to check.",
      href: "/events",
      cta: "Open events",
    });
  }
  if (d.events.processing > 0) {
    alerts.push({
      key: "processing",
      tone: "info",
      icon: <Loader2 className="size-4 animate-spin" aria-hidden="true" />,
      title: `${plural(d.events.processing, "event", "events")} matching now`,
      description: "Face matching is in progress for these events.",
      href: "/events",
      cta: "View progress",
    });
  }
  return alerts;
}

function studentsHint(d: DashboardResponse): string {
  const parts = [`${d.students.enrolled} enrolled`];
  if (d.students.pending > 0) parts.push(`${d.students.pending} pending`);
  if (d.students.failed > 0) parts.push(`${d.students.failed} failed`);
  return parts.join(" · ");
}

function eventsHint(d: DashboardResponse): string {
  const parts = [`${d.events.active} active`];
  if (d.events.archived > 0) parts.push(`${d.events.archived} archived`);
  return parts.join(" · ");
}

function photosHint(d: DashboardResponse): string {
  if (d.media.total === 0) return "No photos yet";
  // BP19c: never say "All matched" over failures — surface pending + failed.
  const parts: string[] = [];
  if (d.media.pending > 0) parts.push(`${d.media.pending} awaiting matching`);
  if (d.media.failed > 0) parts.push(`${d.media.failed} failed`);
  return parts.length > 0 ? parts.join(" · ") : "All matched";
}

export default function DashboardPage() {
  const { dashboard, error, isLoading, mutate } = useDashboard();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={dashboard ? dashboard.school_name : "Dashboard"}
        description="Here's what's happening at your school."
        actions={
          dashboard ? (
            <>
              <Link href="/students" className={buttonVariants({ variant: "secondary", size: "sm" })}>
                <GraduationCap className="size-4" aria-hidden="true" />
                Add student
              </Link>
              <Link href="/events" className={buttonVariants({ variant: "primary", size: "sm" })}>
                <CalendarDays className="size-4" aria-hidden="true" />
                New event
              </Link>
            </>
          ) : undefined
        }
      />
      {isLoading && !dashboard ? (
        <DashboardSkeleton />
      ) : error || !dashboard ? (
        <EmptyState
          role="alert"
          title="Couldn't load your dashboard"
          description="Something went wrong reaching the server."
          action={
            <Button variant="secondary" onClick={() => void mutate()}>
              Try again
            </Button>
          }
        />
      ) : (
        <DashboardBody d={dashboard} />
      )}
    </div>
  );
}

/** Orders the two dashboard layers: the first-run setup checklist (until the school has
 *  distributed) and the command center (stats + alerts, once there's any data). A brand-new
 *  school sees only the checklist — all-zero stat cards would be noise (BP7a). */
function DashboardBody({ d }: { d: DashboardResponse }) {
  const setupComplete = d.setup_checklist.has_distributed;
  const isEmpty = d.students.total === 0 && d.events.total === 0;
  return (
    <div className="flex flex-col gap-6">
      {!setupComplete ? <SetupChecklistCard checklist={d.setup_checklist} /> : null}
      {!isEmpty ? <DashboardContent d={d} /> : null}
    </div>
  );
}

function DashboardContent({ d }: { d: DashboardResponse }) {
  const alerts = buildAlerts(d);
  return (
    <div className="flex flex-col gap-6">
      {alerts.length > 0 ? (
        <Card className="divide-y divide-hairline" role="status">
          {alerts.map((al) => (
            <div key={al.key} className="flex flex-wrap items-center gap-4 p-4">
              <span className={cn("shrink-0", ALERT_ICON_TONE[al.tone])}>{al.icon}</span>
              <div className="flex min-w-0 flex-col">
                <span className="text-body font-medium text-ink">{al.title}</span>
                <span className="text-body-sm text-ink-secondary">{al.description}</span>
              </div>
              <Link
                href={al.href}
                className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "ml-auto shrink-0")}
              >
                {al.cta}
                <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
            </div>
          ))}
        </Card>
      ) : (
        <p className="text-body-sm text-ink-secondary">
          You&apos;re all caught up — nothing needs attention.
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard label="Students" value={d.students.total} hint={studentsHint(d)} href="/students" />
        <StatCard label="Events" value={d.events.total} hint={eventsHint(d)} href="/events" />
        <StatCard label="Photos" value={d.media.total} hint={photosHint(d)} />
      </div>

      {/* Program analytics — rates, trend, per-term (BP14). In the dashboard, not a separate page.
          The primary actions live in the page header (no separate "Quick actions" section). */}
      <ProgramAnalytics />
    </div>
  );
}

/** The first-run setup steps to first value (BP7a). Each ticks off a real dashboard signal;
 *  the whole card retires once the school has distributed. The four core steps are the
 *  critical path (enroll → event → upload → distribute); adding a teacher is **optional**
 *  (a solo school-admin never needs one), so it sits last, doesn't count toward progress,
 *  and never takes the primary CTA. CTAs match the destination page's own button wording
 *  (D6). The first incomplete *core* step gets the primary CTA. */
const CHECKLIST_STEPS: {
  key: keyof DashboardResponse["setup_checklist"];
  label: string;
  href: string;
  cta: string;
  optional?: boolean;
}[] = [
  { key: "has_enrolled_student", label: "Enroll your first student", href: "/students", cta: "Add student" },
  { key: "has_event", label: "Create an event", href: "/events", cta: "New event" },
  { key: "has_media", label: "Upload photos to an event", href: "/events", cta: "Go to events" },
  { key: "has_distributed", label: "Announce to students", href: "/events", cta: "Go to events" },
  { key: "has_staff", label: "Add a teacher", href: "/staff", cta: "Add teacher", optional: true },
];

function SetupChecklistCard({
  checklist,
}: {
  checklist: DashboardResponse["setup_checklist"];
}) {
  const steps = CHECKLIST_STEPS.map((s) => ({ ...s, done: checklist[s.key] }));
  const core = steps.filter((s) => !s.optional);
  const doneCore = core.filter((s) => s.done).length;
  // Primary CTA highlights the first incomplete core step (never the optional one).
  const nextKey = core.find((s) => !s.done)?.key;

  return (
    <Card className="flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Sparkles className="size-5 text-accent-hover" aria-hidden="true" />
          <h2 className="text-headline text-ink">Finish setting up your school</h2>
        </div>
        <span className="text-body-sm tabular-nums text-ink-secondary">
          {doneCore} of {core.length}
        </span>
      </div>
      <p className="text-body-sm text-ink-secondary">
        A few steps to get photos flowing to your students automatically.
      </p>
      <ol className="flex flex-col">
        {steps.map((s) => (
          <li
            key={s.key}
            className="flex items-center gap-3 border-b border-hairline py-3 last:border-b-0"
          >
            {s.done ? (
              <CheckCircle2 className="size-5 shrink-0 text-success-strong" aria-hidden="true" />
            ) : (
              <Circle className="size-5 shrink-0 text-ink-muted" aria-hidden="true" />
            )}
            <span className="sr-only">
              {s.done ? "Completed:" : s.optional ? "Optional:" : "To do:"}
            </span>
            <span
              className={cn(
                "min-w-0 flex-1 text-body",
                s.done ? "text-ink-secondary line-through" : "text-ink",
              )}
            >
              {s.label}
            </span>
            {s.optional && !s.done ? (
              <span className="shrink-0 rounded-full bg-surface-2 px-2 py-0.5 text-body-sm text-ink-secondary">
                Optional
              </span>
            ) : null}
            {!s.done ? (
              <Link
                href={s.href}
                className={cn(
                  buttonVariants({ variant: s.key === nextKey ? "primary" : "ghost", size: "sm" }),
                  "shrink-0",
                )}
              >
                {s.cta}
                <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
            ) : null}
          </li>
        ))}
      </ol>
    </Card>
  );
}

function DashboardSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {[0, 1, 2].map((i) => (
        <Card key={i} className="flex flex-col gap-3 p-5">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-8 w-12" />
          <Skeleton className="h-3 w-28" />
        </Card>
      ))}
    </div>
  );
}
