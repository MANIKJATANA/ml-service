"use client";

import {
  Archive,
  Images,
  MessageCircle,
  Pencil,
  Play,
  RotateCcw,
  ScanSearch,
  Send,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";
import { mutate as globalMutate } from "swr";

import { FilterChips } from "@/components/gallery/filter-chips";
import { SendToAppearingDialog } from "@/components/gallery/send-to-appearing-dialog";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { ProgressBar } from "@/components/ui/progress-bar";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { notifyStudents, processEvent, updateEvent } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { EventProcessingStatus, EventResponse } from "@/lib/api/types";
import {
  derivePillStatus,
  EVENT_INFLIGHT_STALE_MS,
  EVENT_STATUS_LABEL,
  EVENT_STATUS_TONE,
  PROCESSING_LABEL,
  PROCESSING_TONE,
} from "@/lib/events/status";
import { categoryColor } from "@/lib/events/categories";
import { useClasses } from "@/lib/hooks/use-classes";
import { useEvent } from "@/lib/hooks/use-events";
import { useEventCategories } from "@/lib/hooks/use-event-categories";
import { useEventNotifications } from "@/lib/hooks/use-event-notifications";
import { useEventReview } from "@/lib/hooks/use-galleries";
import { useEventStatus } from "@/lib/hooks/use-event-status";
import { cn, formatDate, formatDateTime } from "@/lib/utils";

function EditEventDialog({
  event,
  onSaved,
}: {
  event: EventResponse;
  onSaved: (event: EventResponse) => void;
}) {
  const { toast } = useToast();
  const { categories } = useEventCategories();
  const { classes } = useClasses();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(event.name);
  const [description, setDescription] = useState(event.description ?? "");
  const [eventDate, setEventDate] = useState(event.event_date ?? "");
  const [categoryId, setCategoryId] = useState(event.category_id ?? "");
  const [term, setTerm] = useState(event.term ?? "");
  const [classId, setClassId] = useState(event.student_group_id ?? "");
  const [submitting, setSubmitting] = useState(false);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (next) {
      // Re-seed from the latest event each time it opens.
      setName(event.name);
      setDescription(event.description ?? "");
      setEventDate(event.event_date ?? "");
      setCategoryId(event.category_id ?? "");
      setTerm(event.term ?? "");
      setClassId(event.student_group_id ?? "");
    }
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    // Send only CHANGED fields. BP24: the three tag fields (category/term/class) are now
    // clearable — a changed tag sends its value, an EMPTIED one sends explicit `null` (which
    // the backend's tri-state PATCH clears), and an unchanged one is omitted. name/description/
    // date keep 0027's "empty = leave unchanged" (nothing asks to clear them).
    const patch: {
      name?: string;
      description?: string;
      event_date?: string;
      category_id?: string | null;
      term?: string | null;
      student_group_id?: string | null;
    } = {};
    if (name.trim() && name.trim() !== event.name) patch.name = name.trim();
    if (description.trim() && description.trim() !== (event.description ?? "")) {
      patch.description = description.trim();
    }
    if (eventDate && eventDate !== (event.event_date ?? "")) patch.event_date = eventDate;
    if (categoryId !== (event.category_id ?? "")) patch.category_id = categoryId || null;
    if (term.trim() !== (event.term ?? "")) patch.term = term.trim() || null;
    if (classId !== (event.student_group_id ?? "")) {
      patch.student_group_id = classId || null;
    }
    if (Object.keys(patch).length === 0) {
      toast("No changes to save.", "info");
      setOpen(false);
      return;
    }
    setSubmitting(true);
    try {
      const updated = await updateEvent(event.id, patch);
      toast("Event updated.", "success");
      onSaved(updated);
      setOpen(false);
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="secondary">
          <Pencil className="size-4" aria-hidden="true" />
          Edit
        </Button>
      </DialogTrigger>
      <DialogContent title="Edit event" description="Category, class, and term can be cleared by choosing the empty option.">
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <Field label="Name" htmlFor="edit-event-name">
            <Input
              id="edit-event-name"
              required
              autoFocus
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label="Description" htmlFor="edit-event-description" hint="Optional.">
            <Textarea
              id="edit-event-description"
              maxLength={2000}
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Date" htmlFor="edit-event-date" hint="Optional.">
              <Input
                id="edit-event-date"
                type="date"
                value={eventDate}
                onChange={(e) => setEventDate(e.target.value)}
              />
            </Field>
            <Field label="Category" htmlFor="edit-event-category" hint="Optional.">
              <select
                id="edit-event-category"
                value={categoryId}
                onChange={(e) => setCategoryId(e.target.value)}
                className="h-10 rounded-button border border-hairline bg-canvas px-3 text-body text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {/* BP24: always offer the empty option — selecting it clears the category. */}
                <option value="">No category</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Term" htmlFor="edit-event-term" hint="Optional, e.g. Fall 2026.">
              <Input
                id="edit-event-term"
                maxLength={100}
                value={term}
                onChange={(e) => setTerm(e.target.value)}
              />
            </Field>
            {classes.length > 0 ? (
              <Field label="Class" htmlFor="edit-event-class" hint="Optional.">
                <select
                  id="edit-event-class"
                  value={classId}
                  onChange={(e) => setClassId(e.target.value)}
                  className="h-10 rounded-button border border-hairline bg-canvas px-3 text-body text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {/* BP24: always offer the empty option — selecting it clears the class. */}
                  <option value="">School-wide</option>
                  {classes.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}
          </div>
          <div className="mt-2 flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="secondary">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" loading={submitting}>
              Save changes
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Staff announce controls (BP4): auto-announce toggle, manual "Announce to students", and
 *  the announced/seen roster. Announcing needs a finished (matched) active event. */
// BP24: how many roster rows to show before "Show all" (the roster can be hundreds).
const ROSTER_PREVIEW = 12;

function DistributionCard({
  event,
  refresh,
}: {
  event: EventResponse;
  refresh: () => void;
}) {
  const { toast } = useToast();
  const { roster, mutate: rosterMutate } = useEventNotifications(event.id);
  const { reviews } = useEventReview(event.id);
  const [notifying, setNotifying] = useState(false);
  const [togglingAuto, setTogglingAuto] = useState(false);
  const [confirmAnnounceOpen, setConfirmAnnounceOpen] = useState(false);
  // "Announce on WhatsApp" — the whole-event fan-out (each appearing student gets all the photos
  // they appear in) via the shared preview→confirm→send dialog (no mediaIds = whole event).
  const [waOpen, setWaOpen] = useState(false);
  // BP24 (R3-A2-10): the roster can be hundreds of rows — filter to the actionable "not opened"
  // cohort + collapse behind a preview so "who needs a nudge?" is one click, not an eye-scan.
  const [rosterFilter, setRosterFilter] = useState<"all" | "not_opened">("all");
  const [showAllRoster, setShowAllRoster] = useState(false);
  const rosterStudents = roster?.students ?? [];
  const notOpenedStudents = rosterStudents.filter((s) => !s.seen);
  const filteredRoster =
    rosterFilter === "not_opened" ? notOpenedStudents : rosterStudents;
  const shownRoster = showAllRoster ? filteredRoster : filteredRoster.slice(0, ROSTER_PREVIEW);

  // BP22 (R3-A3-08): the review debt right where Announce lives — Σ ambiguous candidates the
  // read still lists (it already drops corrected pairs, so this is the overlay-correct count).
  const reviewCount = (reviews ?? []).reduce((n, r) => n + r.candidates.length, 0);

  // Announce-able once the event has finished processing at least once, and isn't archived.
  const canNotify = event.completed_at !== null && event.status === "active";

  // Announcing with unreviewed matches shows students uncertain matches — confirm first (no
  // hard block: one click proceeds). Auto-announce is a separate, deliberate opt-in.
  function onAnnounceClick() {
    if (reviewCount > 0) setConfirmAnnounceOpen(true);
    else void onNotify();
  }

  async function onNotify() {
    setNotifying(true);
    try {
      const res = await notifyStudents(event.id);
      toast(
        `Announced to ${res.notified} ${res.notified === 1 ? "student" : "students"} — they'll see it in My Photos.`,
        "success",
      );
      refresh(); // notified_at changed
      void rosterMutate();
      void globalMutate("dashboard"); // A01: announcing flips has_distributed → retire the checklist
    } catch (err) {
      // 400 if archived / not finished; 502 if a channel is unreachable.
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setNotifying(false);
    }
  }

  async function onToggleAuto(next: boolean) {
    setTogglingAuto(true);
    try {
      await updateEvent(event.id, { auto_notify: next });
      refresh();
      void rosterMutate();
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setTogglingAuto(false);
    }
  }

  return (
    <Card className="flex flex-col gap-4 p-6">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-headline text-ink">Announce</h2>
        <StatusPill tone={roster?.announced ? "success" : "neutral"}>
          {roster?.announced ? "Announced" : "Not announced"}
        </StatusPill>
      </div>
      <p className="text-body-sm text-ink-secondary">
        Students see their photos in “My Photos” — in-app only for now. Auto-announce shows them
        there as soon as matching finishes; “Announce to students” does it manually.
      </p>

      <label className="flex items-center gap-3">
        <input
          type="checkbox"
          checked={event.auto_notify}
          disabled={togglingAuto}
          onChange={(e) => void onToggleAuto(e.target.checked)}
          className="size-4 rounded accent-accent-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <span className="text-body text-ink">
          Auto-announce to students when matching finishes
        </span>
      </label>

      {roster?.announced ? (
        <p className="text-body-sm text-ink-secondary">
          Announced to <span className="tabular-nums">{roster.notified_count}</span>{" "}
          {roster.notified_count === 1 ? "student" : "students"} ·{" "}
          <span className="tabular-nums">{roster.seen_count}</span> opened
          {roster.notified_at ? ` · last sent ${formatDate(roster.notified_at)}` : ""}
        </p>
      ) : null}

      <div className="flex flex-col gap-2">
        {reviewCount > 0 ? (
          <Link
            href={`/events/${event.id}/gallery?tab=review`}
            className="inline-flex w-fit items-center gap-2 rounded-button bg-warning-soft px-3 py-1.5 text-body-sm font-medium text-warning-strong transition-colors hover:bg-warning-soft/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ScanSearch className="size-4" aria-hidden="true" />
            {reviewCount} {reviewCount === 1 ? "match" : "matches"} to review
          </Link>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          {/* WhatsApp is the real v1 distribution channel — so it leads. Sends each appearing
              student all the photos they appear in (preview + confirm + budget in the dialog). */}
          <Button onClick={() => setWaOpen(true)} disabled={!canNotify} className="w-fit">
            <MessageCircle className="size-4" aria-hidden="true" />
            Announce on WhatsApp
          </Button>
          {/* The in-app "My Photos" signal (dormant in v1 — no student login) stays available. */}
          <Button
            variant="secondary"
            onClick={onAnnounceClick}
            loading={notifying}
            disabled={!canNotify}
            className="w-fit"
          >
            <Send className="size-4" aria-hidden="true" />
            {roster?.notified_at ? "Re-announce in-app" : "Announce in-app"}
          </Button>
        </div>
        {!canNotify ? (
          <p className="text-body-sm text-ink-secondary">
            Finish matching the photos before announcing.
          </p>
        ) : null}
      </div>

      <ConfirmDialog
        open={confirmAnnounceOpen}
        onOpenChange={setConfirmAnnounceOpen}
        title={`${reviewCount} ${reviewCount === 1 ? "match" : "matches"} still need review`}
        description="Announcing now shows students their photos, including any uncertain matches that haven't been checked. Review them first, or announce anyway."
        confirmLabel="Announce anyway"
        onConfirm={() => {
          setConfirmAnnounceOpen(false);
          void onNotify();
        }}
      />

      {/* Whole-event WhatsApp fan-out (no mediaIds) — preview (who gets how many) → confirm →
          send. All gating (consent, budget, effective overlay, PII) is server-side. */}
      <SendToAppearingDialog eventId={event.id} open={waOpen} onOpenChange={setWaOpen} />

      {rosterStudents.length > 0 ? (
        <div className="flex flex-col gap-2">
          {/* BP24: filter to the actionable "not opened" cohort in one click. */}
          <FilterChips
            ariaLabel="Filter roster"
            items={[
              { id: "all", label: "All", count: rosterStudents.length },
              { id: "not_opened", label: "Not opened", count: notOpenedStudents.length },
            ]}
            activeId={rosterFilter}
            onSelect={(id) => {
              setRosterFilter(id === "not_opened" ? "not_opened" : "all");
              setShowAllRoster(false);
            }}
          />
          {filteredRoster.length === 0 ? (
            <p className="text-body-sm text-ink-secondary" role="status">
              Everyone matched has opened their photos.
            </p>
          ) : (
            <>
              <div className="overflow-hidden rounded-card border border-hairline">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Student</TableHead>
                      <TableHead>Photos</TableHead>
                      <TableHead>Downloaded</TableHead>
                      <TableHead>First opened</TableHead>
                      <TableHead>Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {shownRoster.map((s) => (
                      <TableRow key={s.student_id}>
                        <TableCell>{s.name}</TableCell>
                        <TableCell className="tabular-nums text-ink-secondary">
                          {s.media_count}
                        </TableCell>
                        {/* BP23: downloads + the persistent ever-opened date (unlike the reset-
                            on-reannounce "Opened" status). */}
                        <TableCell className="tabular-nums text-ink-secondary">
                          {s.download_count}
                        </TableCell>
                        <TableCell className="text-ink-secondary">
                          {s.first_seen_at ? formatDate(s.first_seen_at) : "—"}
                        </TableCell>
                        <TableCell>
                          <StatusPill tone={s.seen ? "success" : "neutral"}>
                            {s.seen ? "Opened" : "Not opened"}
                          </StatusPill>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              {filteredRoster.length > ROSTER_PREVIEW ? (
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-fit"
                  onClick={() => setShowAllRoster((v) => !v)}
                >
                  {showAllRoster
                    ? "Show fewer"
                    : `Show all ${filteredRoster.length}`}
                </Button>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </Card>
  );
}

export default function EventDetailPage() {
  const { eventId } = useParams<{ eventId: string }>();
  const { toast } = useToast();
  const { event, isLoading, error, mutate: eventMutate } = useEvent(eventId);
  const { status, isLoading: statusLoading, mutate: statusMutate } = useEventStatus(eventId);

  const [processing, setProcessing] = useState(false);
  const [lifecycleBusy, setLifecycleBusy] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);

  const notFound = isApiError(error) && error.status === 404;

  async function onProcess() {
    if (!event) return;
    setProcessing(true);
    try {
      const updated = await processEvent(event.id);
      await eventMutate(updated, { revalidate: false });
      void globalMutate("events");
      // Optimistically flip status to queued so the pill + poll re-arm at once (even if the
      // refetch is slow or fails); revalidate to pull fresh counts.
      await statusMutate(
        (prev) => (prev ? { ...prev, processing_status: "queued" as const } : prev),
        { revalidate: true },
      );
      toast("Matching started.", "success");
    } catch (err) {
      // 400 archived / already in flight / no pending photos; 502 if the queue is down.
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setProcessing(false);
    }
  }

  async function setLifecycle(next: "active" | "archived") {
    if (!event) return;
    setLifecycleBusy(true);
    try {
      const updated = await updateEvent(event.id, { status: next });
      await eventMutate(updated, { revalidate: false });
      void globalMutate("events");
      toast(next === "archived" ? "Event archived." : "Event restored.", "success");
      setArchiveOpen(false);
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setLifecycleBusy(false);
    }
  }

  const isArchived = event?.status === "archived";
  const proc = status?.processing_status ?? event?.processing_status ?? "not_started";
  const inFlight = proc === "queued" || proc === "processing";
  // BP19a: the job dead-lettered — a terminal, visible failure the operator can retry.
  const isFailed = proc === "failed";
  // The pill must not contradict the counts (a "second batch" of new photos on a completed
  // event should read as unfinished). Shared with the events list via derivePillStatus so
  // both agree; a `failed` event is never overridden (BP19c).
  const pillStatus: EventProcessingStatus = status
    ? derivePillStatus(proc, { total: status.total, pending: status.pending })
    : proc;
  // BP19c staleness (R3-S1-03): a stuck event was indistinguishable from a healthy one. Show
  // how long it's been processing, and past the threshold (19a's guard) escalate + offer Retry.
  // `nowMs` is refreshed in an effect (not read in render — Date.now() is impure there), and
  // ticks every 30s while in-flight so the escalation appears once the threshold is crossed.
  const enqueuedAt = event?.enqueued_at ? new Date(event.enqueued_at) : null;
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!inFlight) return;
    const id = setInterval(() => setNowMs(Date.now()), 30_000);
    return () => clearInterval(id);
  }, [inFlight]);
  const staleInFlight =
    inFlight &&
    enqueuedAt !== null &&
    nowMs - enqueuedAt.getTime() >= EVENT_INFLIGHT_STALE_MS;

  return (
    <div className="flex flex-col gap-6">
      <Breadcrumb
        items={[{ label: "Events", href: "/events" }, { label: event?.name ?? "Event" }]}
      />

      {isLoading ? (
        <>
          <Skeleton className="h-9 w-64" />
          <Card className="flex flex-col gap-3 p-6">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-4 w-32" />
          </Card>
        </>
      ) : error || !event ? (
        <EmptyState
          role="alert"
          title={notFound ? "Event not found" : "Couldn't load event"}
          description={
            notFound ? "It may have been removed." : "Something went wrong reaching the server."
          }
          action={
            notFound ? undefined : (
              <Button variant="secondary" onClick={() => eventMutate()}>
                Retry
              </Button>
            )
          }
        />
      ) : (
        <>
          <PageHeader
            title={event.name}
            actions={
              <>
                {status && status.total > 0 ? (
                  <Link
                    href={`/events/${event.id}/gallery`}
                    className={buttonVariants({ variant: "secondary" })}
                  >
                    <Images className="size-4" aria-hidden="true" />
                    View gallery
                  </Link>
                ) : null}
                <EditEventDialog
                  event={event}
                  onSaved={(e) => eventMutate(e, { revalidate: false })}
                />
                {isArchived ? (
                  <Button
                    variant="secondary"
                    onClick={() => void setLifecycle("active")}
                    loading={lifecycleBusy}
                  >
                    <RotateCcw className="size-4" aria-hidden="true" />
                    Restore
                  </Button>
                ) : (
                  <Button variant="secondary" onClick={() => setArchiveOpen(true)}>
                    <Archive className="size-4" aria-hidden="true" />
                    Archive
                  </Button>
                )}
              </>
            }
          />

          <Card className="p-6">
            <div className="flex flex-col gap-6">
              {event.description ? (
                <p className="whitespace-pre-wrap text-body text-ink-secondary">
                  {event.description}
                </p>
              ) : null}
              <dl className="grid gap-6 sm:grid-cols-3">
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-secondary">Date</dt>
                  <dd className="text-body text-ink">
                    {event.event_date ? formatDate(event.event_date) : "—"}
                  </dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-secondary">Category</dt>
                  <dd>
                    {event.category_id && event.category_name ? (
                      <span
                        className={cn(
                          "inline-block rounded-full px-2.5 py-0.5 text-body-sm font-medium",
                          categoryColor(event.category_id),
                        )}
                      >
                        {event.category_name}
                      </span>
                    ) : (
                      <span className="text-body text-ink-secondary">—</span>
                    )}
                  </dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-secondary">Term</dt>
                  <dd className="text-body text-ink">{event.term ?? "—"}</dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-secondary">Class</dt>
                  <dd className="text-body text-ink">{event.student_group_name ?? "School-wide"}</dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-secondary">Status</dt>
                  <dd>
                    <StatusPill tone={EVENT_STATUS_TONE[event.status]}>
                      {EVENT_STATUS_LABEL[event.status]}
                    </StatusPill>
                  </dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-secondary">Created</dt>
                  <dd className="text-body text-ink">{formatDate(event.created_at)}</dd>
                </div>
                {/* BP23: who created this event (resolved on the detail read). */}
                {event.created_by_email ? (
                  <div className="flex flex-col gap-1">
                    <dt className="text-body-sm text-ink-secondary">Created by</dt>
                    <dd className="text-body text-ink">{event.created_by_email}</dd>
                  </div>
                ) : null}
              </dl>
            </div>
          </Card>

          <Card className="flex flex-col gap-4 p-6">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-headline text-ink">Photos</h2>
              <div className="flex items-center gap-2">
                {/* A18: a live "Matching…" cue that mounts exactly while the status poll runs
                    (inFlight — queued/processing), so it disappears when polling stops. Gated on
                    inFlight, NOT pillStatus (which can read "Completed" with a second batch
                    pending). Decorative (no role="status") — the "Matching since…" aria-live region
                    below is the authoritative announcement. The pulse dot is covered by the global
                    reduced-motion guard. */}
                {inFlight ? (
                  <span
                    className="inline-flex items-center gap-1.5 rounded-full bg-info-soft px-2.5 py-0.5 text-body-sm font-medium text-info-strong"
                    aria-hidden="true"
                  >
                    <span className="size-1.5 rounded-full bg-info-strong animate-pulse" aria-hidden="true" />
                    Matching…
                  </span>
                ) : null}
                <StatusPill tone={PROCESSING_TONE[pillStatus]}>
                  {PROCESSING_LABEL[pillStatus]}
                </StatusPill>
              </div>
            </div>

            {statusLoading && !status ? (
              <div className="flex flex-col gap-2">
                <Skeleton className="h-2 w-full" />
                <Skeleton className="h-4 w-48" />
              </div>
            ) : !status ? (
              <p className="text-body-sm text-ink-secondary">Couldn&apos;t load photo status.</p>
            ) : (
              <>
                {status.total > 0 ? (
                  <>
                    <ProgressBar
                      value={(status.completed / status.total) * 100}
                      label="Matching progress"
                    />
                    <p className="text-body-sm text-ink-secondary">
                      {status.completed} of {status.total} matched
                      {status.pending > 0 ? ` · ${status.pending} pending` : ""}
                      {status.failed > 0 ? ` · ${status.failed} failed` : ""}
                    </p>
                  </>
                ) : (
                  <p className="text-body-sm text-ink-secondary">No photos uploaded yet.</p>
                )}

                {isArchived ? (
                  <p className="text-body-sm text-ink-secondary">
                    Archived — restore the event to add photos or match.
                  </p>
                ) : (
                  <div className="flex flex-wrap items-center gap-2">
                    <Link
                      href={`/events/${event.id}/upload`}
                      className={buttonVariants({
                        variant: status.total === 0 ? "primary" : "secondary",
                      })}
                    >
                      <Upload className="size-4" aria-hidden="true" />
                      {status.total === 0 ? "Upload photos" : "Add more photos"}
                    </Link>
                    {(!inFlight && (status.pending > 0 || status.failed > 0 || isFailed)) ||
                    staleInFlight ? (
                      <Button onClick={onProcess} loading={processing}>
                        <Play className="size-4" aria-hidden="true" />
                        {isFailed || staleInFlight
                          ? "Retry"
                          : status.pending > 0
                            ? proc === "completed"
                              ? "Match again"
                              : "Match photos"
                            : "Retry failed"}
                      </Button>
                    ) : null}
                  </div>
                )}

                <div aria-live="polite">
                  {/* BP19c: show how long it's been processing (a stuck event was
                      indistinguishable from a healthy one), and escalate past the threshold. */}
                  {!isArchived && inFlight ? (
                    <p
                      className={
                        staleInFlight
                          ? "text-body-sm text-warning-strong"
                          : "text-body-sm text-ink-secondary"
                      }
                    >
                      {enqueuedAt
                        ? `Matching since ${formatDateTime(event.enqueued_at as string)}`
                        : "Matching"}{" "}
                      — this updates automatically.
                      {staleInFlight
                        ? " This is taking longer than usual; you can retry below."
                        : ""}
                    </p>
                  ) : null}
                  {/* BP19a: the whole job dead-lettered (not just some photos) — a terminal,
                      retryable failure. Retry re-runs it once the cause is fixed. */}
                  {!isArchived && isFailed ? (
                    <p className="text-body-sm text-error-strong">
                      Matching couldn&apos;t finish — the job stopped before completing. This is
                      usually temporary; retry to run it again. If it keeps failing, an
                      administrator may need to check the matching service.
                    </p>
                  ) : null}
                  {!isArchived && !inFlight && !isFailed && status.failed > 0 ? (
                    <p className="text-body-sm text-warning-strong">
                      {status.failed} {status.failed === 1 ? "photo" : "photos"} couldn&apos;t
                      be matched. Retry — if it keeps failing, the file may be corrupt or
                      unreadable, so replace it.
                    </p>
                  ) : null}
                  {!isArchived && !inFlight && !isFailed && status.total > 0 &&
                  status.pending === 0 && status.failed === 0 ? (
                    <p className="text-body-sm text-success-strong">All photos matched.</p>
                  ) : null}
                </div>
              </>
            )}
          </Card>

          <DistributionCard event={event} refresh={() => void eventMutate()} />
        </>
      )}

      <ConfirmDialog
        open={archiveOpen}
        onOpenChange={setArchiveOpen}
        title="Archive event?"
        description="Its photos are kept, but it's hidden from active workflows. You can restore it anytime."
        confirmLabel="Archive event"
        loading={lifecycleBusy}
        onConfirm={() => void setLifecycle("archived")}
      />
    </div>
  );
}
