"use client";

import { Images } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { mutate as globalMutate } from "swr";

import { FilterChips } from "@/components/gallery/filter-chips";
import { GridSkeleton } from "@/components/gallery/grid-skeleton";
import { PhotoGrid } from "@/components/gallery/photo-grid";
import { SendToAppearingDialog } from "@/components/gallery/send-to-appearing-dialog";
import { SignedImage } from "@/components/gallery/signed-image";
import { StudentChipPicker } from "@/components/gallery/student-chip-picker";
import { StudentPhotoActions } from "@/components/gallery/student-photo-actions";
import { StudentRefAvatar } from "@/components/gallery/student-ref-avatar";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { batchReview, undoCorrection } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { GalleryMediaResponse, MediaType } from "@/lib/api/types";
import { toISODate } from "@/lib/events/calendar";
import { useDownloadAll } from "@/lib/hooks/use-download-all";
import { useEvent } from "@/lib/hooks/use-events";
import {
  useEventMedia,
  useEventReview,
  useEventStudentMedia,
  useEventStudents,
} from "@/lib/hooks/use-galleries";
import { useStudent } from "@/lib/hooks/use-students";
import { cn, sanitizeFilename } from "@/lib/utils";

function AllPhotos({ eventId }: { eventId: string }) {
  const { items, total, isLoading, isLoadingMore, error, reachedEnd, loadMore, mutate } =
    useEventMedia(eventId);
  const { toast } = useToast();
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sendOpen, setSendOpen] = useState(false);
  const selectedIds = [...selected];
  const { busy, done, total: dlTotal, cap: dlCap, onDownloadAll } = useDownloadAll(selectedIds);
  const isInitialLoading = isLoading && items.length === 0;

  function exitSelect() {
    setSelectMode(false);
    setSelected(new Set());
  }
  function toggleSelect(id: string) {
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  async function downloadSelected() {
    if (selectedIds.length === 0) return;
    try {
      // BP24: unify on the honest toast (mirrors the student page) — distinguish a user-cancel
      // (silent, stay in select mode) from a partial / capped / all-failed save.
      const { saved, capped, cancelled } = await onDownloadAll();
      if (cancelled) return; // dismissed the save dialog — no false "success"
      if (saved === 0) {
        toast("Couldn't download those photos. Please try again.", "error");
        return; // stay in select mode so they can retry
      }
      if (capped) {
        toast(
          `Saved the first ${dlCap} of ${dlTotal} photos. To get the rest, select fewer at a time, or use desktop Chrome or Edge.`,
          "info",
          { sticky: true },
        );
      } else if (saved < dlTotal) {
        toast(
          `Saved ${saved} of ${dlTotal} photos — ${dlTotal - saved} couldn't be saved right now. Try again.`,
          "info",
          { sticky: true },
        );
      } else {
        toast(`Downloaded ${saved} ${saved === 1 ? "photo" : "photos"}.`, "success");
      }
      exitSelect();
    } catch {
      toast("Couldn't download those photos. Please try again.", "error");
    }
  }

  if (isInitialLoading) return <GridSkeleton />;
  if (error) {
    return (
      <EmptyState
        role="alert"
        title="Couldn't load photos"
        description="Something went wrong reaching the server."
        action={
          <Button variant="secondary" onClick={() => mutate()}>
            Retry
          </Button>
        }
      />
    );
  }
  if (total === 0) {
    return (
      <EmptyState
        icon={<Images className="size-8" aria-hidden="true" />}
        title="No photos yet"
        description="Upload photos to this event to see them here."
      />
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-end gap-3">
        {selectMode ? (
          <>
            <span className="mr-auto text-body-sm text-ink" role="status">
              {selected.size} selected
              {busy ? ` · downloading ${done} of ${dlTotal}` : ""}
            </span>
            {/* Fan out the selected photos to whoever appears in them (a preview confirms first). */}
            <Button
              size="sm"
              onClick={() => setSendOpen(true)}
              disabled={selected.size === 0 || busy}
            >
              Send to appearing students
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={downloadSelected}
              loading={busy}
              disabled={selected.size === 0}
            >
              Download {selected.size > 0 ? selected.size : ""}
            </Button>
            <Button size="sm" variant="ghost" onClick={exitSelect} disabled={busy}>
              Done
            </Button>
          </>
        ) : (
          <Button size="sm" variant="secondary" onClick={() => setSelectMode(true)}>
            Select photos
          </Button>
        )}
      </div>
      <PhotoGrid
        items={items.map((m) => ({
          id: m.id,
          mediaType: m.media_type,
          hasThumbnail: m.thumbnail_path !== null,
        }))}
        canManageAppearances
        onLoadMore={loadMore}
        hasMore={!reachedEnd}
        loadingMore={isLoadingMore}
        selectionMode={selectMode}
        selectedIds={selected}
        onToggleSelect={toggleSelect}
      />
      <SendToAppearingDialog
        eventId={eventId}
        mediaIds={selectedIds}
        open={sendOpen}
        onOpenChange={setSendOpen}
        onSent={exitSelect}
      />
    </div>
  );
}

/** The picked student's photos in THIS event — the shared select/send/download UX
 *  (`StudentPhotoActions`, decisions/0100 + its event-gallery follow-on): browse (lightbox +
 *  appearance editing) OR a per-photo Select mode (Select all / Select random N / manual taps) →
 *  Send/Download exactly the chosen subset (or the whole set in browse). Reuses the download
 *  entitlement (both staff roles hold `gallery:view_all`) + the effective set the tab already
 *  shows — no backend change, no widening. `useEvent` is SWR-deduped with the page's own call.
 *  Hooks run before the early returns (Rules of Hooks). */
function EventStudentPhotos({
  eventId,
  studentId,
  studentName,
}: {
  eventId: string;
  studentId: string;
  studentName: string;
}) {
  const { media, isLoading, error } = useEventStudentMedia(eventId, studentId);
  const { event } = useEvent(eventId);
  // W2: the picked student's opt-in/number for the WhatsApp send (not on the roster row).
  const { student } = useStudent(studentId);

  // `new Date()` in a lazy initializer runs once at mount, not on every render.
  const [zipStamp] = useState(() => toISODate(new Date()));
  const datePart = event?.event_date ?? "photo";
  // A single-event view → flat, event-date-named zip entries (no per-event folder).
  const zipEntryFor = useCallback(
    (_m: GalleryMediaResponse, i: number) => `${datePart}-${String(i + 1).padStart(3, "0")}`,
    [datePart],
  );
  const eventPart = event ? sanitizeFilename(event.name) : "";
  const zipName = `${sanitizeFilename(studentName) || "student"}${
    eventPart ? `-${eventPart}` : ""
  }-photos-${zipStamp}.zip`;

  if (isLoading) return <GridSkeleton />;
  if (error) return <p className="text-body-sm text-ink-secondary">Couldn&apos;t load photos.</p>;
  if (!media || media.length === 0) {
    return <p className="text-body-sm text-ink-secondary">No photos for this student.</p>;
  }
  return (
    <StudentPhotoActions
      media={media}
      studentId={studentId}
      studentName={studentName}
      optedIn={student?.whatsapp_opt_in ?? false}
      hasNumber={student?.mobile_number != null}
      resetKey={studentId}
      zipEntryFor={zipEntryFor}
      zipName={zipName}
      leftHeader={
        <p className="text-body-sm text-ink-secondary">
          {media.length} {media.length === 1 ? "photo" : "photos"} in this event
        </p>
      }
    />
  );
}

// A big event matches many students; show this many top (by photo-count) quick chips beside a
// searchable picker for the rest (mirrors the student page's "Appears in" events filter).
const QUICK_STUDENTS = 4;

function ByStudent({ eventId }: { eventId: string }) {
  const { students, isLoading, error, mutate } = useEventStudents(eventId);
  const [picked, setPicked] = useState<string | null>(null);

  if (isLoading) return <GridSkeleton />;
  if (error) {
    return (
      <EmptyState
        role="alert"
        title="Couldn't load students"
        description="Something went wrong reaching the server."
        action={
          <Button variant="secondary" onClick={() => mutate()}>
            Retry
          </Button>
        }
      />
    );
  }
  if (!students || students.length === 0) {
    return (
      <EmptyState
        title="No students matched yet"
        description="Match this event's photos — students who appear in them show up here."
      />
    );
  }

  // Most-matched first, so the quick chips + the default pick are the students most likely wanted.
  const sorted = [...students].sort((a, b) => b.media_count - a.media_count);
  // Derived (stale-safe): if a background revalidation drops the picked student, fall back to the
  // top student — a stale pick can never strand the tab or fetch a gone student.
  const activeId =
    picked !== null && students.some((s) => s.student_id === picked)
      ? picked
      : sorted[0].student_id;
  const activeStudent = students.find((s) => s.student_id === activeId);

  // Quick chips: the top few matched students; if a non-quick student is picked (via the picker),
  // surface them as a chip too so the selection stays visible + deselectable (mirrors the events
  // filter on the student page).
  const quick = sorted.slice(0, QUICK_STUDENTS);
  const quickIds = new Set(quick.map((s) => s.student_id));
  const chipStudents =
    activeStudent && !quickIds.has(activeStudent.student_id) ? [...quick, activeStudent] : quick;
  const hasMoreStudents = students.length > chipStudents.length; // a picker helps beyond the quick set

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-2">
        <FilterChips
          ariaLabel="Students"
          items={chipStudents.map((s) => ({
            id: s.student_id,
            label: s.name,
            count: s.media_count,
          }))}
          activeId={activeId}
          onSelect={setPicked}
        />
        {hasMoreStudents ? (
          <StudentChipPicker students={students} activeId={activeId} onPick={setPicked} />
        ) : null}
      </div>
      <EventStudentPhotos
        eventId={eventId}
        studentId={activeId}
        studentName={activeStudent?.name ?? "student"}
      />
    </div>
  );
}

/** One ambiguous match awaiting a decision — a (photo, candidate-student) pair. */
type ReviewPair = {
  key: string;
  mediaId: string;
  mediaType: MediaType;
  studentId: string;
  name: string;
  confidence: number;
};

/** The batch review lane (BP13): every ambiguous match flattened to a per-student decision,
 *  sorted by confidence, with checkboxes → Confirm/Reject selected + a guarded "Reject all
 *  remaining". Each decision is exactly the single confirm/reject (BP5), applied to many. */
function NeedsReview({ eventId }: { eventId: string }) {
  const { reviews, isLoading, error, mutate } = useEventReview(eventId);
  const { toast } = useToast();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [rejectAllOpen, setRejectAllOpen] = useState(false);
  const [view, setView] = useState<"grid" | "table">("grid");
  // BP30: the last reject batch, for a discoverable inline Undo (not a toast — it hosts an
  // async button). Captured BEFORE the lane refetches so the pair ids survive the mutate.
  const [lastRejected, setLastRejected] = useState<ReviewPair[]>([]);
  const [undoing, setUndoing] = useState(false);
  const [thresholdInput, setThresholdInput] = useState("");

  // Flatten photos → per-candidate pairs, highest confidence first (the obvious ones on top).
  const pairs = useMemo<ReviewPair[]>(() => {
    const out: ReviewPair[] = [];
    for (const r of reviews ?? []) {
      for (const c of r.candidates) {
        out.push({
          key: `${r.media_id}|${c.student_id}`,
          mediaId: r.media_id,
          mediaType: r.media_type,
          studentId: c.student_id,
          name: c.name,
          confidence: c.confidence,
        });
      }
    }
    out.sort((a, b) => b.confidence - a.confidence);
    return out;
  }, [reviews]);

  async function apply(keys: string[], verdict: "confirmed" | "rejected") {
    if (keys.length === 0) return;
    setBusy(true);
    try {
      const byKey = new Map(pairs.map((p) => [p.key, p]));
      const resolved = keys
        .map((k) => byKey.get(k))
        .filter((p): p is ReviewPair => p !== undefined);
      const verdicts = resolved.map((p) => ({
        media_id: p.mediaId,
        student_id: p.studentId,
        verdict,
      }));
      const { applied } = await batchReview(eventId, verdicts);
      toast(
        `${verdict === "confirmed" ? "Confirmed" : "Rejected"} ${applied} ${applied === 1 ? "match" : "matches"}.`,
        "success",
      );
      // BP30: stash the rejected pairs (captured before the lane refetches) so we can offer a
      // one-click Undo. A confirm/new-reject batch replaces this — see below.
      setLastRejected(verdict === "rejected" ? resolved : []);
      setSelected(new Set());
      await mutate();
      void globalMutate("dashboard"); // the "N to review" badge drops
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setBusy(false);
    }
  }

  // BP30: revert the just-rejected pairs to raw-ML needs_review pending — they reappear in the
  // lane. allSettled so a pair a colleague already re-decided fails harmlessly.
  async function undoLast() {
    if (lastRejected.length === 0) return;
    setUndoing(true);
    try {
      await Promise.allSettled(
        lastRejected.map((p) => undoCorrection(p.mediaId, p.studentId)),
      );
      await mutate();
      void globalMutate("dashboard");
      setLastRejected([]);
    } finally {
      setUndoing(false);
    }
  }

  if (isLoading) return <GridSkeleton />;
  if (error) {
    return (
      <EmptyState
        role="alert"
        title="Couldn't load review items"
        description="Something went wrong reaching the server."
        action={
          <Button variant="secondary" onClick={() => mutate()}>
            Retry
          </Button>
        }
      />
    );
  }
  if (pairs.length === 0) {
    return (
      <EmptyState
        title="Nothing to review"
        description="Ambiguous matches show up here to confirm or reject. You're all caught up."
      />
    );
  }

  const allSelected = selected.size === pairs.length;
  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(pairs.map((p) => p.key)));
  }
  function toggle(key: string) {
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  // BP30: select every pair below a confidence threshold (%). REPLACES the selection — nothing
  // auto-applies; the human still clicks Confirm/Reject to commit (no auto-confirm invariant).
  function selectBelow(pct: number) {
    setSelected(
      new Set(
        pairs
          .filter((p) => p.confidence != null && Math.round(p.confidence * 100) < pct)
          .map((p) => p.key),
      ),
    );
  }
  function applyFreeThreshold() {
    const n = Number(thresholdInput);
    if (!Number.isFinite(n) || thresholdInput.trim() === "") return;
    selectBelow(Math.min(100, Math.max(0, n)));
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-body-sm text-ink">
          <input
            type="checkbox"
            checked={allSelected}
            onChange={toggleAll}
            className="size-4 rounded border-hairline text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          Select all
          <span className="text-ink-secondary">
            · {selected.size} of {pairs.length} selected · sorted by confidence
          </span>
        </label>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => apply([...selected], "confirmed")} loading={busy} disabled={selected.size === 0}>
            Confirm {selected.size > 0 ? selected.size : ""}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => apply([...selected], "rejected")}
            loading={busy}
            disabled={selected.size === 0}
          >
            Reject {selected.size > 0 ? selected.size : ""}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setRejectAllOpen(true)}
            disabled={busy}
          >
            Reject all remaining
          </Button>
        </div>
      </div>

      {/* BP30: quick-select the low-confidence matches (only stages a selection) + a view toggle. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-body-sm text-ink-secondary">
        <span className="text-ink">Select below</span>
        {[60, 70, 80].map((n) => (
          <Button key={n} size="sm" variant="secondary" onClick={() => selectBelow(n)}>
            &lt; {n}%
          </Button>
        ))}
        <span className="flex items-center gap-1.5">
          <input
            type="number"
            min={0}
            max={100}
            inputMode="numeric"
            value={thresholdInput}
            onChange={(e) => setThresholdInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                applyFreeThreshold();
              }
            }}
            aria-label="Confidence threshold percent"
            placeholder="%"
            className="w-16 rounded-button border border-hairline bg-canvas px-2 py-1 text-ink tabular-nums focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <Button
            size="sm"
            variant="secondary"
            onClick={applyFreeThreshold}
            disabled={thresholdInput.trim() === ""}
          >
            Apply
          </Button>
        </span>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-ink">View</span>
          <Button
            size="sm"
            variant={view === "grid" ? "primary" : "secondary"}
            onClick={() => setView("grid")}
            aria-pressed={view === "grid"}
          >
            Grid
          </Button>
          <Button
            size="sm"
            variant={view === "table" ? "primary" : "secondary"}
            onClick={() => setView("table")}
            aria-pressed={view === "table"}
          >
            Table
          </Button>
        </div>
      </div>

      {/* BP30: discoverable batch-undo — inline (not a toast, it hosts an async button). */}
      {lastRejected.length > 0 ? (
        <div
          role="status"
          className="flex flex-wrap items-center gap-3 rounded-card border border-hairline bg-surface-2 px-3 py-2 text-body-sm text-ink"
        >
          <span>
            Rejected {lastRejected.length} {lastRejected.length === 1 ? "match" : "matches"}.
          </span>
          <Button size="sm" variant="secondary" onClick={undoLast} loading={undoing}>
            Undo
          </Button>
        </div>
      ) : null}

      {view === "grid" ? (
        <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {pairs.map((p) => {
            const isSel = selected.has(p.key);
            return (
              <li key={p.key}>
                <div
                  className={cn(
                    "overflow-hidden rounded-card border transition-colors",
                    isSel ? "border-accent-hover ring-2 ring-ring" : "border-hairline",
                  )}
                >
                  <label className="relative block cursor-pointer">
                    <input
                      type="checkbox"
                      checked={isSel}
                      onChange={() => toggle(p.key)}
                      aria-label={`Select match for ${p.name}`}
                      className="absolute left-2 top-2 z-10 size-5 rounded border-hairline bg-canvas text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    />
                    <SignedImage
                      mediaId={p.mediaId}
                      kind={p.mediaType}
                      size="thumb"
                      alt=""
                      loading="square"
                      className="aspect-square w-full"
                      // Uniform square crop (matches PhotoTile) so review-lane thumbs are all one size.
                      imgClassName="block aspect-square w-full object-cover align-top"
                      fallbackText="Unavailable"
                    />
                  </label>
                  <div className="flex flex-col gap-1 p-3">
                    <div className="flex items-center gap-2">
                      {/* BP22: the candidate's reference face — decide by looking, not guessing. */}
                      <StudentRefAvatar studentId={p.studentId} name={p.name} className="size-7" />
                      <p className="min-w-0 flex-1 truncate text-body-sm text-ink" title={p.name}>
                        {p.name}
                      </p>
                      <span className="shrink-0 tabular-nums text-body-sm text-ink-secondary">
                        {Math.round(p.confidence * 100)}%
                      </span>
                    </div>
                    <Link
                      href={`/photos/${p.mediaId}`}
                      className="rounded text-body-sm font-medium text-accent-hover hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      Open photo →
                    </Link>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <ul className="flex flex-col divide-y divide-hairline rounded-card border border-hairline">
          {pairs.map((p) => {
            const isSel = selected.has(p.key);
            return (
              <li
                key={p.key}
                className={cn(
                  "flex items-center gap-3 px-3 py-2 transition-colors",
                  isSel ? "bg-surface-2" : null,
                )}
              >
                <input
                  type="checkbox"
                  checked={isSel}
                  onChange={() => toggle(p.key)}
                  aria-label={`Select match for ${p.name}`}
                  className="size-4 shrink-0 rounded border-hairline text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
                <SignedImage
                  mediaId={p.mediaId}
                  kind={p.mediaType}
                  size="thumb"
                  alt=""
                  loading="square"
                  className="size-11 shrink-0 overflow-hidden rounded-button"
                  imgClassName="block size-full object-cover align-top"
                  fallbackText=""
                />
                <StudentRefAvatar studentId={p.studentId} name={p.name} className="size-8 shrink-0" />
                <span className="min-w-0 flex-1 truncate text-body-sm text-ink" title={p.name}>
                  {p.name}
                </span>
                <span className="shrink-0 tabular-nums text-body-sm text-ink-secondary">
                  {Math.round(p.confidence * 100)}%
                </span>
                <Link
                  href={`/photos/${p.mediaId}`}
                  className="shrink-0 rounded text-body-sm font-medium text-accent-hover hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  Open photo →
                </Link>
              </li>
            );
          })}
        </ul>
      )}

      <ConfirmDialog
        open={rejectAllOpen}
        onOpenChange={setRejectAllOpen}
        title="Reject all remaining?"
        description={`This rejects the remaining ${pairs.length} ${pairs.length === 1 ? "match" : "matches"} and hides those photos from the students in them. You can undo individual rejections later.`}
        confirmLabel="Reject all"
        loading={busy}
        onConfirm={() => apply(pairs.map((p) => p.key), "rejected")}
      />
    </div>
  );
}

const GALLERY_TABS = ["all", "by-student", "review"] as const;
type GalleryTab = (typeof GALLERY_TABS)[number];

export default function EventGalleryPage() {
  const { eventId } = useParams<{ eventId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { event } = useEvent(eventId);
  const { reviews } = useEventReview(eventId);
  // Count match PAIRS (sum of candidates), not photos — a photo can carry several ambiguous
  // candidates. Same unit + overlay the DistributionCard uses; the school-wide dashboard "N to
  // review" is a close approximation (raw minus resolved, clamped), not necessarily bit-exact.
  const reviewCount = (reviews ?? []).reduce((n, r) => n + r.candidates.length, 0);

  // BP22 (R3-A3-09): the active tab lives in the URL so a deep-link opens the right tab and
  // browser-back returns to it (the route is dynamic, so useSearchParams needs no Suspense).
  const tabParam = searchParams.get("tab");
  const tab: GalleryTab = GALLERY_TABS.includes(tabParam as GalleryTab)
    ? (tabParam as GalleryTab)
    : "all";
  function onTabChange(value: string) {
    router.replace(`/events/${eventId}/gallery?tab=${value}`, { scroll: false });
  }

  return (
    <div className="flex flex-col gap-6">
      <Breadcrumb
        items={[
          { label: "Events", href: "/events" },
          { label: event?.name ?? "Event", href: `/events/${eventId}` },
          { label: "Gallery" },
        ]}
      />
      <PageHeader title="Gallery" description="Browse every photo, or see who appears in them." />

      <Tabs value={tab} onValueChange={onTabChange}>
        <TabsList>
          <TabsTrigger value="all">All photos</TabsTrigger>
          <TabsTrigger value="by-student">By student</TabsTrigger>
          <TabsTrigger value="review">
            Needs review{reviewCount > 0 ? ` (${reviewCount})` : ""}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="all">
          <AllPhotos eventId={eventId} />
        </TabsContent>
        <TabsContent value="by-student">
          <ByStudent eventId={eventId} />
        </TabsContent>
        <TabsContent value="review">
          <NeedsReview eventId={eventId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
