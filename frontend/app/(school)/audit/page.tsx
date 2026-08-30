"use client";

import { ChevronLeft, ChevronRight, Download, ScrollText } from "lucide-react";
import Link from "next/link";
import { Suspense, useState } from "react";
import useSWR from "swr";

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
import { useToast } from "@/components/ui/toast";
import { ROLE_LABELS } from "@/lib/auth/routes";
import { getDownloadLog, getEvents, getStudents } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import { saveCsv, toCsv } from "@/lib/csv";
import { useDownloadLog } from "@/lib/hooks/use-audit";
import { useUrlParams } from "@/lib/hooks/use-url-state";
import { formatDateTime } from "@/lib/utils";

const PAGE_SIZE = 50;
// The picker options are bounded (a select, not a search) — the house style for a filter over
// a moderately-sized set; a school with more events/students than this filters by the others.
const PICKER_LIMIT = 200;
// The export walks the full filtered set in bounded pages (never the whole table at once).
const EXPORT_PAGE = 200;
const EXPORT_CAP = 10000; // guard a pathologically large export

const SELECT_CLASS =
  "h-10 rounded-button border border-hairline bg-canvas px-3 text-body text-ink " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** The four actor-role filter options (backend accepts any Role; these are the meaningful ones
 *  for a school download log — a platform admin never downloads a school's photos). */
const ROLE_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All roles" },
  { value: "school_admin", label: "School admins" },
  { value: "teacher", label: "Teachers" },
  { value: "student", label: "Students" },
];

export default function AuditLogPage() {
  // school_admin only (a teacher in the (school) group is redirected home — the backend
  // also 403s `audit:view`); the fetch below never fires for a disallowed role.
  return (
    <RoleGate allow={["school_admin"]}>
      {/* URL-backed filters (BP28a) need a Suspense boundary (useSearchParams, static route). */}
      <Suspense fallback={<Skeleton className="h-24 w-full" />}>
        <AuditContent />
      </Suspense>
    </RoleGate>
  );
}

/** Convert a `<input type="date">` value (YYYY-MM-DD, empty when unset) to an inclusive
 *  day-boundary ISO timestamp, or undefined. `end=true` → end-of-day; else start-of-day. UTC so
 *  it matches the stored `created_at` (the backend compares `>=`/`<=` against a UTC column). */
function dayBoundaryIso(date: string, end: boolean): string | undefined {
  if (!date) return undefined;
  return `${date}T${end ? "23:59:59.999" : "00:00:00.000"}Z`;
}

function AuditContent() {
  const { get, set } = useUrlParams();
  const { toast } = useToast();

  // Filters + offset live in the URL (shareable + Back-safe), mirroring the students page.
  const eventId = get("event"); // "" = all events
  const studentId = get("student"); // "" = all students
  const role = get("role"); // "" = all roles
  const fromDate = get("from"); // YYYY-MM-DD
  const toDate = get("to");
  const offset = Number(get("offset", "0")) || 0;

  const createdFrom = dayBoundaryIso(fromDate, false);
  const createdTo = dayBoundaryIso(toDate, true);

  const filterParams = {
    eventId: eventId || undefined,
    studentId: studentId || undefined,
    actorRole: role || undefined,
    createdFrom,
    createdTo,
  } as const;

  const { page, error, isLoading, mutate } = useDownloadLog({
    limit: PAGE_SIZE,
    offset,
    ...filterParams,
  });

  // Bounded picker options (admin-only, cheap): the first page of events + students by name.
  const { data: eventsPage } = useSWR("audit-picker-events", () =>
    getEvents({ limit: PICKER_LIMIT, offset: 0 }),
  );
  const { data: studentsPage } = useSWR("audit-picker-students", () =>
    getStudents({ limit: PICKER_LIMIT, offset: 0 }),
  );
  const events = eventsPage?.items ?? [];
  const students = studentsPage?.items ?? [];

  const [exporting, setExporting] = useState(false);

  const items = page?.items ?? [];
  const total = page?.total ?? 0;
  const start = total === 0 ? 0 : offset + 1;
  const end = offset + items.length;
  const canPrev = offset > 0;
  const canNext = end < total;
  const isFiltering =
    eventId !== "" || studentId !== "" || role !== "" || fromDate !== "" || toDate !== "";

  /** Fetch the FULL filtered set (in bounded pages) and save it as a CSV. */
  async function exportCsv() {
    setExporting(true);
    try {
      const rows: string[][] = [];
      let off = 0;
      let capped = false;
      for (;;) {
        const p = await getDownloadLog({ limit: EXPORT_PAGE, offset: off, ...filterParams });
        for (const r of p.items) {
          rows.push([
            r.downloaded_at, // raw ISO — a spreadsheet parses/sorts it cleanly
            r.actor_email ?? "Removed account",
            ROLE_LABELS[r.actor_role],
            r.event_name ?? "",
            r.media_id,
            r.subject_student_name ?? "",
          ]);
        }
        off += EXPORT_PAGE;
        if (rows.length >= EXPORT_CAP) {
          capped = off < p.total; // more rows remain beyond the cap → the export is truncated
          break;
        }
        if (p.items.length < EXPORT_PAGE || off >= p.total) break;
      }
      if (rows.length === 0) {
        toast("Nothing to export for this filter.", "info");
        return;
      }
      const csv = toCsv(
        ["When", "Actor email", "Actor role", "Event", "Photo", "Student (self)"],
        rows,
      );
      const date = new Date().toISOString().slice(0, 10);
      saveCsv(`access-log-${date}.csv`, csv);
      if (capped) {
        toast(
          `Exported the first ${rows.length.toLocaleString()} downloads — narrow the date range to get the rest.`,
          "info",
          { sticky: true },
        );
      } else {
        toast(`Exported ${rows.length} download${rows.length === 1 ? "" : "s"}.`, "success");
      }
    } catch (err) {
      toast(isApiError(err) ? err.message : "Couldn't export the access log.", "error");
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Access log"
        description="Records photo saves made in the app — who, what, and when (newest first). It records in-app downloads only, not views or a right-click save on an open image."
        actions={
          <Button
            variant="secondary"
            onClick={exportCsv}
            loading={exporting}
            disabled={exporting || total === 0}
          >
            <Download className="size-4" aria-hidden="true" />
            Export CSV
          </Button>
        }
      />

      {/* Filters: event / student / actor role / date range. Any change resets offset to 0 in
          the SAME set() call (the page's URL is the single source of truth). */}
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-body-sm text-ink-secondary">
          Event
          <select
            aria-label="Filter by event"
            value={eventId}
            onChange={(e) => set({ event: e.target.value || null, offset: null })}
            className={SELECT_CLASS}
          >
            <option value="">All events</option>
            {events.map((ev) => (
              <option key={ev.id} value={ev.id}>
                {ev.name}
              </option>
            ))}
            {events.length === PICKER_LIMIT ? (
              <option value="" disabled>
                Showing first {PICKER_LIMIT} — filter by date for the rest
              </option>
            ) : null}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-body-sm text-ink-secondary">
          Student
          <select
            aria-label="Filter by student"
            value={studentId}
            onChange={(e) => set({ student: e.target.value || null, offset: null })}
            className={SELECT_CLASS}
          >
            <option value="">All students</option>
            {students.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
            {students.length === PICKER_LIMIT ? (
              <option value="" disabled>
                Showing first {PICKER_LIMIT} — filter by date for the rest
              </option>
            ) : null}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-body-sm text-ink-secondary">
          Role
          <select
            aria-label="Filter by role"
            value={role}
            onChange={(e) => set({ role: e.target.value || null, offset: null })}
            className={SELECT_CLASS}
          >
            {ROLE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-body-sm text-ink-secondary">
          From
          <input
            type="date"
            aria-label="From date"
            value={fromDate}
            max={toDate || undefined}
            onChange={(e) => set({ from: e.target.value || null, offset: null })}
            className={SELECT_CLASS}
          />
        </label>
        <label className="flex flex-col gap-1 text-body-sm text-ink-secondary">
          To
          <input
            type="date"
            aria-label="To date"
            value={toDate}
            min={fromDate || undefined}
            onChange={(e) => set({ to: e.target.value || null, offset: null })}
            className={SELECT_CLASS}
          />
        </label>
        {isFiltering ? (
          <Button
            variant="ghost"
            onClick={() =>
              set({ event: null, student: null, role: null, from: null, to: null, offset: null })
            }
          >
            Clear filters
          </Button>
        ) : null}
      </div>

      {fromDate || toDate ? (
        <p className="-mt-3 text-body-sm text-ink-secondary">Date filters use UTC.</p>
      ) : null}

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
            title={isFiltering ? "No downloads match" : "No downloads yet"}
            description={
              isFiltering
                ? "Try a wider date range or a different filter."
                : "Downloads will appear here as staff and students save photos."
            }
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
                    <TableHead>Student (self)</TableHead>
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
                          <span className="text-body-sm text-ink-secondary">
                            {ROLE_LABELS[row.actor_role]}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Link
                          href={`/photos/${row.media_id}`}
                          className="rounded text-accent-hover hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
              <p className="text-body-sm text-ink-secondary" aria-live="polite">
                Showing {start}–{end} of {total}
              </p>
              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  onClick={() => {
                    const prev = Math.max(0, offset - PAGE_SIZE);
                    // offset 0 = page 1 → drop the param for a clean URL (null clears it).
                    set({ offset: prev > 0 ? String(prev) : null });
                  }}
                  disabled={!canPrev}
                >
                  <ChevronLeft className="size-4" aria-hidden="true" />
                  Previous
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => set({ offset: String(offset + PAGE_SIZE) })}
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
