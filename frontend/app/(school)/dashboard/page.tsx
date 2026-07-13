"use client";

import {
  AlertTriangle,
  ArrowRight,
  CalendarDays,
  GraduationCap,
  Loader2,
  ScanSearch,
  Send,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

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
  const { events_undistributed, enrollment_failures, needs_review } = d.needs_attention;
  if (events_undistributed > 0) {
    alerts.push({
      key: "undistributed",
      tone: "warning",
      icon: <Send className="size-4" aria-hidden="true" />,
      title: `${plural(events_undistributed, "event", "events")} ready to distribute`,
      description: "Photos are uploaded but haven't been sent to students yet.",
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
      href: "/students",
      cta: "Fix enrollments",
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
      icon: <Loader2 className="size-4" aria-hidden="true" />,
      title: `${plural(d.events.processing, "event", "events")} distributing now`,
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
  return d.media.pending > 0 ? `${d.media.pending} awaiting processing` : "All processed";
}

export default function DashboardPage() {
  const { dashboard, error, isLoading, mutate } = useDashboard();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={dashboard ? dashboard.school_name : "Dashboard"}
        description="Here's what's happening at your school."
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
      ) : dashboard.students.total === 0 && dashboard.events.total === 0 ? (
        <FirstRun />
      ) : (
        <DashboardContent d={dashboard} />
      )}
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
        <p className="text-body-sm text-ink-muted">
          You&apos;re all caught up — nothing needs attention.
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard label="Students" value={d.students.total} hint={studentsHint(d)} href="/students" />
        <StatCard label="Events" value={d.events.total} hint={eventsHint(d)} href="/events" />
        <StatCard label="Photos" value={d.media.total} hint={photosHint(d)} />
      </div>

      <div className="flex flex-col gap-3">
        <h2 className="text-headline text-ink">Quick actions</h2>
        <div className="flex flex-wrap gap-2">
          <Link href="/students" className={buttonVariants({ variant: "secondary" })}>
            <GraduationCap className="size-4" aria-hidden="true" />
            Add student
          </Link>
          <Link href="/events" className={buttonVariants({ variant: "secondary" })}>
            <CalendarDays className="size-4" aria-hidden="true" />
            New event
          </Link>
        </div>
      </div>
    </div>
  );
}

/** Fresh school (no students, no events): an invitation to the first step, not a placeholder. */
function FirstRun() {
  return (
    <EmptyState
      icon={<Sparkles className="size-8" aria-hidden="true" />}
      title="Let's set up your school"
      description="Add students and enroll their faces, then create an event and upload photos — matched photos are distributed to each student automatically."
      action={
        <div className="flex flex-wrap justify-center gap-2">
          <Link href="/students" className={buttonVariants({ variant: "primary" })}>
            Add students
          </Link>
          <Link href="/events" className={buttonVariants({ variant: "secondary" })}>
            Create an event
          </Link>
        </div>
      }
    />
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
