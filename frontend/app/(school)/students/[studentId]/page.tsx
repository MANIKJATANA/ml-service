"use client";

import {
  AlertTriangle,
  Ban,
  CircleCheck,
  Download,
  ImagePlus,
  KeyRound,
  Pencil,
  RefreshCw,
  Shuffle,
  SquareCheck,
  Trash2,
} from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { type FormEvent, useCallback, useMemo, useState } from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { EventPicker } from "@/components/gallery/event-picker";
import { FilterChips } from "@/components/gallery/filter-chips";
import { GridSkeleton } from "@/components/gallery/grid-skeleton";
import { PhotoGrid } from "@/components/gallery/photo-grid";
import { type Invite, InviteResultDialog } from "@/components/staff/invite-result-dialog";
import { StudentAvatar } from "@/components/ui/avatar";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { FileDropzone } from "@/components/ui/file-dropzone";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { ProgressBar } from "@/components/ui/progress-bar";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { useToast } from "@/components/ui/toast";
import { SendPhotosButton } from "@/components/whatsapp/send-photos-button";
import {
  deleteStudent,
  enrollStudent,
  getStudentEngagement,
  resendStudentInvite,
  setStudentClass,
  setStudentReferencePhoto,
  setStudentStatus,
  updateStudentMobile,
} from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type {
  EnrollmentFailureReason,
  EventForStudentResponse,
  GalleryMediaResponse,
  StudentResponse,
  UserStatus,
} from "@/lib/api/types";
import { uploadReferencePhoto } from "@/lib/api/upload";
import { formatEventDate, toISODate } from "@/lib/events/calendar";
import { useClasses } from "@/lib/hooks/use-classes";
import { useDownloadAll } from "@/lib/hooks/use-download-all";
import { useAllStudentMedia, useStudentEvents, useStudentMedia } from "@/lib/hooks/use-galleries";
import { useStudentReferencePhoto } from "@/lib/hooks/use-student-reference-photo";
import { useStudent } from "@/lib/hooks/use-students";
import { ENROLL_FAILURE_HELP, enrollDisplay } from "@/lib/students/enrollment";
import { formatDate, sanitizeFilename } from "@/lib/utils";

/** Why an enrollment failed + how to fix it (BP7b). Shown under the profile when the
 *  status is `failed`; the specific copy comes from the reason the backend recorded. */
function EnrollmentFailureNote({ reason }: { reason: EnrollmentFailureReason | null }) {
  const help = reason ? ENROLL_FAILURE_HELP[reason] : null;
  return (
    <Card role="alert" className="flex items-start gap-3 border-error/30 bg-error/5 p-4">
      <AlertTriangle className="mt-0.5 size-5 shrink-0 text-error" aria-hidden="true" />
      <div className="flex flex-col gap-1">
        <p className="text-body-sm font-medium text-ink">
          {help ? help.title : "Enrollment failed"}
        </p>
        <p className="text-body-sm text-ink-secondary">
          {help ? help.fix : "Replace the reference photo with a clearer one."}
        </p>
      </div>
    </Card>
  );
}

/** Add (photoless student) or replace (fix a bad photo) a reference photo, then re-enroll
 *  (BP7d-2). Uploads straight to Supabase, then PUTs the object path; the caller refreshes
 *  from the returned, freshly-enrolled student. */
function ReferencePhotoDialog({
  studentId,
  hasPhoto,
  onUpdated,
}: {
  studentId: string;
  hasPhoto: boolean;
  onUpdated: (student: StudentResponse) => void;
}) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [uploadedPath, setUploadedPath] = useState<string | null>(null); // survives a failed PUT
  const [progress, setProgress] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const label = hasPhoto ? "Replace photo" : "Add photo";

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      setFile(null);
      setUploadedPath(null);
      setProgress(null);
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      toast("Please choose a reference photo.", "error");
      return;
    }
    setSubmitting(true);
    try {
      // Upload the photo, then set it (the backend generates the BP17 thumbnail + re-enrolls).
      // Memoize the path so a failed backend PUT doesn't re-upload on retry.
      let objectPath = uploadedPath;
      if (!objectPath) {
        setProgress(0);
        objectPath = await uploadReferencePhoto(file, setProgress);
        setProgress(null);
        setUploadedPath(objectPath);
      }
      const updated = await setStudentReferencePhoto(studentId, objectPath);
      handleOpenChange(false);
      onUpdated(updated);
      toast(
        updated.enrollment_status === "enrolled"
          ? "Photo saved and enrolled."
          : "Photo saved, but enrollment didn't succeed — check the reason.",
        updated.enrollment_status === "enrolled" ? "success" : "warning",
      );
    } catch (err) {
      setProgress(null);
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="secondary" disabled={submitting}>
          <ImagePlus className="size-4" aria-hidden="true" />
          {label}
        </Button>
      </DialogTrigger>
      <DialogContent
        title={label}
        description="Uploads the photo and enrolls the student's face. A clear, front-facing photo works best."
      >
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          {/* A08: say what the reference photo is FOR — it enrolls the student's face. */}
          <FileDropzone
            file={file}
            onFileChange={(next) => {
              setFile(next);
              setUploadedPath(null); // a new file must be re-uploaded
            }}
            disabled={submitting}
            hint="This photo enrolls the student's face for matching — a clear, front-facing photo works best (up to 30 MB)."
          />
          {progress !== null ? (
            <div className="flex flex-col gap-1.5">
              <ProgressBar value={progress} label="Upload progress" />
              <span aria-live="polite" className="text-body-sm text-ink-secondary">
                Uploading photo… {progress}%
              </span>
            </div>
          ) : null}
          <div className="mt-2 flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="secondary">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" loading={submitting}>
              {label}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Assign/change/clear the student's class (BP11a). A compact inline select in the profile;
 *  writes through `setStudentClass` and refreshes the student + the class-count caches. */
function ClassSelect({
  studentId,
  current,
  onChanged,
}: {
  studentId: string;
  current: string | null;
  onChanged: (student: StudentResponse) => void;
}) {
  const { toast } = useToast();
  const { classes } = useClasses();
  const [saving, setSaving] = useState(false);

  async function onChange(value: string) {
    setSaving(true);
    try {
      const updated = await setStudentClass(studentId, value || null);
      onChanged(updated);
      void globalMutate("students"); // the list shows a class badge
      void globalMutate("classes"); // and the classes list shows member counts
      toast(value ? "Class updated." : "Removed from class.", "success");
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <select
      aria-label="Class"
      value={current ?? ""}
      disabled={saving}
      onChange={(e) => onChange(e.target.value)}
      className="h-9 rounded-button border border-hairline bg-canvas px-2.5 text-body-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
    >
      <option value="">No class</option>
      {classes.map((c) => (
        <option key={c.id} value={c.id}>
          {c.name}
        </option>
      ))}
    </select>
  );
}

/** The loose client-side mobile shape (mirrors the backend `domain/phones.py` gate) — only a
 *  pre-flight; the server validates authoritatively (and the provider validates at send time). */
const MOBILE_RE = /^\+?[0-9]{7,15}$/;

/** Set/clear the student's WhatsApp contact + opt-in (Phase 0). A compact dialog with a `tel`
 *  input + an opt-in checkbox; writes through `updateStudentMobile` and refreshes the student.
 *  Modeled on `ClassSelect` — the mobile edit isn't a governance action (no audit). */
function MobileEditor({
  studentId,
  mobile,
  optIn,
  onChanged,
}: {
  studentId: string;
  mobile: string | null;
  optIn: boolean;
  onChanged: (student: StudentResponse) => void;
}) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(mobile ?? "");
  const [wantOptIn, setWantOptIn] = useState(optIn);
  const [saving, setSaving] = useState(false);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (next) {
      // Re-seed from the current student each time the dialog opens.
      setValue(mobile ?? "");
      setWantOptIn(optIn);
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = value.trim();
    if (trimmed && !MOBILE_RE.test(trimmed)) {
      toast("Enter a valid mobile number (7–15 digits, optional leading +).", "error");
      return;
    }
    setSaving(true);
    try {
      const updated = await updateStudentMobile(studentId, trimmed || null, wantOptIn);
      onChanged(updated);
      handleOpenChange(false);
      toast("WhatsApp contact updated.", "success");
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="secondary" className="h-8 px-2.5 text-body-sm">
          <Pencil className="size-3.5" aria-hidden="true" />
          Edit
        </Button>
      </DialogTrigger>
      <DialogContent
        title="WhatsApp contact"
        description="An optional mobile number for WhatsApp, plus whether the student has opted in. Leave the number blank to clear it."
      >
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <Field
            label="Mobile number"
            htmlFor="student-mobile"
            hint="Include the country code (e.g. +14155550123). Optional — leave blank to clear."
          >
            <Input
              id="student-mobile"
              type="tel"
              autoComplete="off"
              maxLength={32}
              disabled={saving}
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          </Field>
          <div className="flex flex-col gap-1">
            <label htmlFor="student-optin" className="flex items-center gap-3">
              <input
                id="student-optin"
                type="checkbox"
                checked={wantOptIn}
                disabled={saving}
                onChange={(e) => setWantOptIn(e.target.checked)}
                aria-describedby="student-optin-hint"
                className="size-4 rounded accent-accent-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <span className="text-body text-ink">Opted in to WhatsApp messages</span>
            </label>
            <p id="student-optin-hint" className="text-body-sm text-ink-secondary">
              They&apos;ll receive their photos on WhatsApp once delivery is turned on.
            </p>
          </div>
          <div className="mt-2 flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="secondary">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" loading={saving}>
              Save
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** One student's reach + engagement (BP23) — events/photos they appear in, how many they've
 *  opened + when, and their own downloads. Its own read (staff-only). Renders nothing on a
 *  load/error so it never blocks the profile. */
function EngagementCard({ studentId }: { studentId: string }) {
  const { data } = useSWR(`student-engagement:${studentId}`, () =>
    getStudentEngagement(studentId),
  );
  if (!data) return null;
  const stats: { label: string; value: string }[] = [
    { label: "Events they're in", value: data.events_appearing.toLocaleString() },
    { label: "Photos they're in", value: data.photos_appearing.toLocaleString() },
    { label: "Events opened", value: data.events_opened.toLocaleString() },
    {
      label: "Last opened",
      value: data.last_opened_at ? formatDate(data.last_opened_at) : "—",
    },
    { label: "Downloads", value: data.downloads.toLocaleString() },
  ];
  return (
    <Card className="flex flex-col gap-4 p-6">
      <h2 className="text-headline text-ink">Engagement</h2>
      <dl className="grid gap-6 sm:grid-cols-3">
        {stats.map((s) => (
          <div key={s.label} className="flex flex-col gap-1">
            <dt className="text-body-sm text-ink-secondary">{s.label}</dt>
            <dd className="text-body font-medium tabular-nums text-ink">{s.value}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

// A student appears in a bounded number of events; show "All" + this many latest event chips
// beside it, with a searchable picker for the rest (decisions/0100).
const QUICK_EVENTS = 3;
const ALL_VIEW = "__all__"; // the "All events" chip id (not a real event id)
const DEFAULT_RANDOM = 10; // the default "select random N" count

/** event_id → {name, date} for photo captions + zip foldering. */
function eventMetaOf(events: EventForStudentResponse[]) {
  const m = new Map<string, { name: string; date: string | null }>();
  for (const e of events) m.set(e.event_id, { name: e.name, date: e.event_date });
  return m;
}

/** Pick up to `n` random media ids (Fisher–Yates partial shuffle; browser `Math.random`). */
function pickRandomIds(media: GalleryMediaResponse[], n: number): Set<string> {
  const ids = media.map((m) => m.media_id);
  for (let i = ids.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [ids[i], ids[j]] = [ids[j], ids[i]];
  }
  return new Set(ids.slice(0, Math.max(0, Math.min(n, ids.length))));
}

/** Download a GIVEN set of the student's photos as ONE zip — foldered/named by event/date. Reuses
 *  the download entitlement (both staff roles hold `gallery:view_all`) + the streaming
 *  `useDownloadAll` — no backend change (BP26 v1 / decisions/0081: staff download → share). The
 *  `mediaList` is the ACTIVE target (the current view, or the current selection — decisions/0100),
 *  so the zip re-keys when the view/selection changes. Its count is the EFFECTIVE set (BP5
 *  corrections applied) — so it can differ from the EngagementCard's raw `photos_appearing`. */
function PhotoDownloadButton({
  mediaList,
  studentName,
  eventMeta,
}: {
  mediaList: GalleryMediaResponse[];
  studentName: string;
  eventMeta: Map<string, { name: string; date: string | null }>;
}) {
  const { toast } = useToast();
  // `new Date()` in a lazy initializer runs once at mount, not on every render.
  const [zipStamp] = useState(() => toISODate(new Date()));
  const mediaIds = useMemo(() => mediaList.map((m) => m.media_id), [mediaList]);
  const entryBase = useCallback(
    (i: number) => {
      const m = mediaList[i];
      const meta = m ? eventMeta.get(m.event_id) : undefined;
      const folder = (meta && sanitizeFilename(meta.name)) || "Photos";
      const datePart = meta?.date ?? "photo";
      return `${folder}/${datePart}-${String(i + 1).padStart(3, "0")}`;
    },
    [mediaList, eventMeta],
  );
  const zipName = `${sanitizeFilename(studentName) || "student"}-photos-${zipStamp}.zip`;
  const { busy, done, total, cap, onDownloadAll } = useDownloadAll(mediaIds, {
    entryBase,
    zipName,
  });

  async function handleDownload() {
    try {
      const { saved, capped, cancelled } = await onDownloadAll();
      if (cancelled) return; // dismissed the save dialog — silent, not an error
      // Copy mirrors the sibling staff surface (the event-gallery download) for consistency.
      if (saved === 0) {
        toast("Couldn't download the photos. Please try again.", "error");
      } else if (capped) {
        toast(
          `Saved the first ${cap} of ${total} photos. To get the rest, open this page in desktop Chrome or Edge.`,
          "info",
          { sticky: true },
        );
      } else if (saved < total) {
        toast(
          `Saved ${saved} of ${total} photos — ${total - saved} couldn't be saved right now. Try again.`,
          "info",
          { sticky: true },
        );
      } else {
        toast(`Downloaded ${total} ${total === 1 ? "photo" : "photos"}.`, "success");
      }
    } catch {
      toast("Couldn't prepare the download. Please try again.", "error");
    }
  }

  return (
    <div className="flex items-center gap-3">
      <Button
        variant="secondary"
        onClick={handleDownload}
        loading={busy}
        disabled={busy || total === 0}
      >
        <Download className="size-4" aria-hidden="true" />
        {busy
          ? `Preparing ${done}/${total}…`
          : `Download ${total} ${total === 1 ? "photo" : "photos"}`}
      </Button>
      {/* SR-only progress (mirrors the student self-view): a *visible* per-tick live region would
          announce on every photo; the button-label flip covers sighted users. */}
      {busy ? (
        <span className="sr-only" aria-live="polite">
          Preparing {done} of {total} photos
        </span>
      ) : null}
    </div>
  );
}

/** Events the student appears in, with a smart filter (All + the latest events + a searchable
 *  picker) and a per-photo SELECT mode so staff send/download EXACTLY the photos they want
 *  (decisions/0100). Browse mode: tiles open the lightbox and the actions target the whole current
 *  view; Select mode: tiles toggle, and "Select all"/"Select random N"/manual taps build the
 *  target. Hidden until the student has been matched into at least one photo (decisions/0035).
 *  `optedIn`/`hasNumber` gate the WhatsApp send (disabled with a reason hint). */
function AppearsInSection({
  studentId,
  studentName,
  optedIn,
  hasNumber,
}: {
  studentId: string;
  studentName: string;
  optedIn: boolean;
  hasNumber: boolean;
}) {
  const { events, isLoading, error } = useStudentEvents(studentId);
  // The student's whole EFFECTIVE set (the "All" view + its count); a specific event fetches its own.
  const { media: allMedia } = useAllStudentMedia(studentId);
  const [picked, setPicked] = useState<string | null>(null); // null = "All"
  // Derived (stale-safe, like the class/category filters — "derived, not effect-reconciled"): if a
  // background revalidation drops the picked event, fall back to "All" — a stale pick can never
  // strand the section or fetch a gone event.
  const activePicked =
    picked !== null && events?.some((e) => e.event_id === picked) ? picked : null;
  const { media: eventMedia } = useStudentMedia(studentId, activePicked); // null → not fetched

  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [randomN, setRandomN] = useState(DEFAULT_RANDOM);

  // Clear the selection whenever the view changes (stale-safe; adjust-state-during-render, so a
  // selection can never act on photos from a different view).
  const [prevView, setPrevView] = useState(activePicked);
  if (prevView !== activePicked) {
    setPrevView(activePicked);
    setSelected(new Set());
  }

  const eventMeta = useMemo(() => eventMetaOf(events ?? []), [events]);

  // The photos currently in view: "All" → the whole effective set; else the picked event's.
  const viewMedia = activePicked === null ? allMedia : eventMedia;
  // What the actions act on: the selection (Select mode) or the whole view (Browse).
  const targetMedia = useMemo(() => {
    const list = viewMedia ?? [];
    return selectMode ? list.filter((m) => selected.has(m.media_id)) : list;
  }, [viewMedia, selectMode, selected]);
  const targetIds = useMemo(() => targetMedia.map((m) => m.media_id), [targetMedia]);

  if (isLoading) {
    return (
      <Card className="flex flex-col gap-4 p-6">
        <Skeleton className="h-5 w-32" />
        <GridSkeleton />
      </Card>
    );
  }
  if (error || !events || events.length === 0) return null;

  // Quick chips: "All" + the latest events (newest-first, undated last); if a non-quick event is
  // picked (via the picker), surface it as a chip too so it's visible + deselectable.
  const sorted = [...events].sort((a, b) => {
    if (a.event_date === b.event_date) return 0;
    if (a.event_date === null) return 1;
    if (b.event_date === null) return -1;
    return a.event_date < b.event_date ? 1 : -1;
  });
  const latest = sorted.slice(0, QUICK_EVENTS);
  const quickIds = new Set(latest.map((e) => e.event_id));
  const pickedEvent = activePicked ? events.find((e) => e.event_id === activePicked) : null;
  const chipEvents =
    pickedEvent && !quickIds.has(pickedEvent.event_id) ? [...latest, pickedEvent] : latest;
  const chipItems = [
    { id: ALL_VIEW, label: "All", count: allMedia?.length },
    ...chipEvents.map((e) => ({ id: e.event_id, label: e.name, count: e.media_count })),
  ];
  const hasMoreEvents = events.length > chipEvents.length; // a picker helps beyond the quick set
  const viewCount = viewMedia?.length ?? 0;

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function exitSelect() {
    setSelectMode(false);
    setSelected(new Set());
  }

  const gridItems = (viewMedia ?? []).map((m) => {
    // In "All" the photos span events → caption each with its event (BP20); a single-event view
    // doesn't need it.
    let caption: string | undefined;
    if (activePicked === null) {
      const meta = eventMeta.get(m.event_id);
      if (meta) {
        const d = formatEventDate(meta.date);
        caption = d ? `${meta.name} · ${d}` : meta.name;
      }
    }
    return {
      id: m.media_id,
      mediaType: m.media_type,
      hasThumbnail: m.has_thumbnail,
      caption,
    };
  });

  return (
    <Card className="flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-headline text-ink">Appears in</h2>
        {selectMode ? (
          <Button variant="secondary" size="sm" onClick={exitSelect}>
            Done
          </Button>
        ) : (
          <Button variant="secondary" size="sm" onClick={() => setSelectMode(true)}>
            <SquareCheck className="size-4" aria-hidden="true" />
            Select photos
          </Button>
        )}
      </div>

      {/* Phase 2: "All" + latest chips, plus a searchable picker for a long event history. */}
      <div className="flex flex-wrap items-center gap-2">
        <FilterChips
          ariaLabel="Events"
          items={chipItems}
          activeId={activePicked ?? ALL_VIEW}
          onSelect={(id) => setPicked(id === ALL_VIEW ? null : id)}
        />
        {hasMoreEvents ? (
          <EventPicker events={events} activeId={activePicked} onPick={setPicked} />
        ) : null}
      </div>

      {/* Phase 3: in Select mode, build the target — all of this view, a random sample, or taps. */}
      {selectMode ? (
        <div className="flex flex-wrap items-center gap-2 rounded-button bg-surface px-3 py-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setSelected(new Set((viewMedia ?? []).map((m) => m.media_id)))}
            disabled={viewCount === 0}
          >
            Select all ({viewCount})
          </Button>
          <div className="flex items-center gap-1.5">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setSelected(pickRandomIds(viewMedia ?? [], randomN))}
              disabled={viewCount === 0}
            >
              <Shuffle className="size-4" aria-hidden="true" />
              Select random
            </Button>
            <input
              type="number"
              min={1}
              max={Math.max(1, viewCount)}
              // Show a value that's honest for the CURRENT view (never > its count) while `randomN`
              // preserves the user's intent for a bigger view; `pickRandomIds` also clamps.
              value={Math.min(randomN, Math.max(1, viewCount))}
              onChange={(e) => setRandomN(Math.max(1, Number(e.target.value) || 1))}
              aria-label="Number of random photos"
              className="h-8 w-16 rounded-button border border-hairline bg-canvas px-2 text-body-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setSelected(new Set())}
            disabled={selected.size === 0}
          >
            Clear
          </Button>
          <span role="status" className="ml-auto text-body-sm text-ink-secondary">
            {selected.size} selected
          </span>
        </div>
      ) : null}

      {/* The grid — Select mode toggles tiles; Browse opens the lightbox (+ appearance editing). */}
      {viewMedia === undefined ? (
        <GridSkeleton />
      ) : viewMedia.length === 0 ? (
        <p className="text-body-sm text-ink-secondary">No photos in this view.</p>
      ) : selectMode ? (
        <PhotoGrid
          items={gridItems}
          selectionMode
          selectedIds={selected}
          onToggleSelect={toggleSelect}
          showAppearances={false}
        />
      ) : (
        <PhotoGrid items={gridItems} canManageAppearances />
      )}

      {/* Actions — target the selection (Select mode) or the whole view (Browse). Shown once the
          view has loaded, so Send never flashes "Send 0" during the fetch. */}
      {viewMedia !== undefined && viewMedia.length > 0 ? (
        <div className="flex flex-wrap items-center gap-3">
          <SendPhotosButton
            studentId={studentId}
            studentName={studentName}
            mediaIds={targetIds}
            optedIn={optedIn}
            hasNumber={hasNumber}
          />
          <PhotoDownloadButton
            mediaList={targetMedia}
            studentName={studentName}
            eventMeta={eventMeta}
          />
        </div>
      ) : null}
    </Card>
  );
}

export default function StudentDetailPage() {
  const { studentId } = useParams<{ studentId: string }>();
  const router = useRouter();
  const { toast } = useToast();
  const { student, isLoading, error, mutate } = useStudent(studentId);
  // BP17: the header avatar's reference-photo thumbnail (full size for the larger avatar),
  // gated on a non-null path so a photoless student skips the fetch. Falls back to initials.
  const { photoUrl } = useStudentReferencePhoto(
    studentId,
    student?.reference_photo_path != null,
    "full",
  );

  const [reenrolling, setReenrolling] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [sending, setSending] = useState(false);
  const [statusSaving, setStatusSaving] = useState(false);
  const [disableConfirmOpen, setDisableConfirmOpen] = useState(false);
  const [invite, setInvite] = useState<Invite | null>(null);

  const notFound = isApiError(error) && error.status === 404;

  async function onReenroll() {
    setReenrolling(true);
    try {
      const updated = await enrollStudent(studentId);
      await mutate(updated, { revalidate: false });
      void globalMutate("students"); // keep the list's enrollment pill in sync
      toast(
        updated.enrollment_status === "enrolled"
          ? "Re-enrolled."
          : "Enrollment didn't succeed — check the reason below.",
        updated.enrollment_status === "enrolled" ? "success" : "warning",
      );
    } catch (err) {
      // ML-down isn't a throw here — enroll returns 200 with status "failed" (the warning
      // branch above). This only fires on 404 / expired-session / network failures.
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setReenrolling(false);
    }
  }

  async function onResend() {
    setSending(true);
    try {
      // BP18a: recovery WITHOUT the destructive delete — regenerates the temp password,
      // shown once. The student's photos + matches are untouched.
      const { student: s, temp_password } = await resendStudentInvite(studentId);
      setInvite({ email: s.email, tempPassword: temp_password });
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setSending(false);
    }
  }

  async function onToggleStatus(next: UserStatus) {
    setStatusSaving(true);
    try {
      // BP18d: a non-destructive kill-switch — a disabled student can't sign in but keeps
      // every photo + match row (unlike delete). Reversible: re-enable restores access.
      const updated = await setStudentStatus(studentId, next);
      await mutate(updated, { revalidate: false });
      void globalMutate("students"); // keep the list in sync
      toast(next === "disabled" ? "Login disabled." : "Login enabled.", "success");
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setStatusSaving(false);
      setDisableConfirmOpen(false);
    }
  }

  async function onDelete() {
    setDeleting(true);
    try {
      await deleteStudent(studentId);
      void globalMutate("students"); // drop the deleted row from the list cache
      void globalMutate(`students/${studentId}`, undefined, { revalidate: false }); // and its stale detail entry
      toast("Student deleted.", "success");
      router.push("/students");
      router.refresh();
    } catch (err) {
      // 502 = ML delete failed (embeddings must be removed first) — operator retries.
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
      setDeleting(false);
      setConfirmOpen(false);
    }
  }

  async function onPhotoUpdated(updated: StudentResponse) {
    await mutate(updated, { revalidate: false });
    void globalMutate("students"); // keep the list's enrollment pill in sync
  }

  return (
    <div className="flex flex-col gap-6">
      <Breadcrumb
        items={[{ label: "Students", href: "/students" }, { label: student?.name ?? "Student" }]}
      />

      {isLoading ? (
        <>
          <Skeleton className="h-9 w-64" />
          <Card className="flex flex-col gap-3 p-6">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-4 w-32" />
          </Card>
        </>
      ) : error || !student ? (
        <EmptyState
          role="alert"
          title={notFound ? "Student not found" : "Couldn't load student"}
          description={
            notFound ? "It may have been removed." : "Something went wrong reaching the server."
          }
          action={
            notFound ? undefined : (
              <Button variant="secondary" onClick={() => mutate()}>
                Retry
              </Button>
            )
          }
        />
      ) : (
        <>
          <PageHeader
            title={student.name}
            actions={
              <>
                <ReferencePhotoDialog
                  studentId={studentId}
                  hasPhoto={student.reference_photo_path !== null}
                  onUpdated={onPhotoUpdated}
                />
                {/* Re-enroll retries the STORED photo — hidden for a photoless student
                    (they'd 400); use "Add photo" instead. */}
                {student.reference_photo_path !== null ? (
                  <Button
                    variant="secondary"
                    onClick={onReenroll}
                    loading={reenrolling}
                    disabled={deleting || sending}
                  >
                    <RefreshCw className="size-4" aria-hidden="true" />
                    Re-enroll
                  </Button>
                ) : null}
                {/* BP18a: give a locked-out student a fresh password without deleting them
                    (delete would erase their photo history). */}
                <Button
                  variant="secondary"
                  onClick={onResend}
                  loading={sending}
                  disabled={reenrolling || deleting || statusSaving}
                >
                  <KeyRound className="size-4" aria-hidden="true" />
                  Send new password
                </Button>
                {/* BP18d: a non-destructive kill-switch — disable a student's login without
                    deleting them (delete erases their photo history). Enabling is direct;
                    disabling asks first (it locks the student out until re-enabled). */}
                {student.status === "disabled" ? (
                  <Button
                    variant="secondary"
                    onClick={() => onToggleStatus("active")}
                    loading={statusSaving}
                    disabled={reenrolling || sending || deleting}
                  >
                    <CircleCheck className="size-4" aria-hidden="true" />
                    Enable login
                  </Button>
                ) : (
                  <Button
                    variant="secondary"
                    onClick={() => setDisableConfirmOpen(true)}
                    disabled={reenrolling || sending || deleting || statusSaving}
                  >
                    <Ban className="size-4" aria-hidden="true" />
                    Disable login
                  </Button>
                )}
                <Button
                  variant="destructive"
                  onClick={() => setConfirmOpen(true)}
                  disabled={reenrolling || sending || statusSaving}
                >
                  <Trash2 className="size-4" aria-hidden="true" />
                  Delete
                </Button>
              </>
            }
          />
          <Card className="p-6">
            <div className="flex flex-col gap-6">
              <div className="flex items-center gap-4">
                <StudentAvatar
                  name={student.name}
                  photoUrl={photoUrl}
                  className="size-12 text-body"
                />
                <div className="flex flex-col gap-0.5">
                  <span className="text-headline text-ink">{student.name}</span>
                  <span className="text-body-sm text-ink-secondary">{student.email}</span>
                </div>
              </div>
              <dl className="grid gap-6 sm:grid-cols-2">
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-secondary">Enrollment</dt>
                  <dd>
                    <StatusPill tone={enrollDisplay(student).tone}>
                      {enrollDisplay(student).label}
                    </StatusPill>
                  </dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-secondary">Login</dt>
                  <dd>
                    <StatusPill tone={student.status === "disabled" ? "neutral" : "success"}>
                      {student.status === "disabled" ? "Disabled" : "Active"}
                    </StatusPill>
                  </dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-secondary">Added</dt>
                  <dd className="text-body text-ink">{formatDate(student.created_at)}</dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-secondary">Class</dt>
                  <dd>
                    <ClassSelect
                      studentId={studentId}
                      current={student.student_group_id}
                      onChanged={(updated) => {
                        void mutate(updated, { revalidate: false });
                      }}
                    />
                  </dd>
                </div>
                {/* Phase 0: the WhatsApp contact — number + opt-in state + an inline editor. */}
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-secondary">WhatsApp</dt>
                  <dd className="flex items-center gap-3">
                    <span className="text-body text-ink">
                      {student.mobile_number ?? "—"}
                    </span>
                    <StatusPill
                      tone={student.whatsapp_opt_in ? "success" : "neutral"}
                    >
                      {student.whatsapp_opt_in ? "Opted in" : "Not opted in"}
                    </StatusPill>
                    <MobileEditor
                      studentId={studentId}
                      mobile={student.mobile_number}
                      optIn={student.whatsapp_opt_in}
                      onChanged={(updated) => {
                        void mutate(updated, { revalidate: false });
                      }}
                    />
                  </dd>
                </div>
              </dl>
            </div>
          </Card>
          {student.enrollment_status === "failed" ? (
            <div className="flex flex-col gap-3">
              <EnrollmentFailureNote reason={student.enrollment_failure_reason} />
              {/* F01: the fix action right beside the note. A transient ML outage just needs a
                  re-run of the stored photo; a bad/absent photo needs a new one — the same
                  ReferencePhotoDialog whose label auto-flips Add/Replace. */}
              <div>
                {student.enrollment_failure_reason === "ml_unavailable" ? (
                  <Button variant="secondary" onClick={onReenroll} loading={reenrolling} disabled={deleting || sending}>
                    <RefreshCw className="size-4" aria-hidden="true" />
                    Re-enroll
                  </Button>
                ) : (
                  <ReferencePhotoDialog
                    studentId={studentId}
                    hasPhoto={student.reference_photo_path !== null}
                    onUpdated={onPhotoUpdated}
                  />
                )}
              </div>
            </div>
          ) : null}
          <EngagementCard studentId={studentId} />
          <AppearsInSection
            studentId={studentId}
            studentName={student.name}
            optedIn={student.whatsapp_opt_in}
            hasNumber={student.mobile_number != null}
          />
        </>
      )}

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Delete student?"
        description="Permanently deletes their login, profile, face enrollment, and their matched-photo history (which photos they appear in) — this can't be undone. The event photos themselves stay in every gallery, and past download records are kept but anonymized."
        confirmLabel="Delete student"
        destructive
        loading={deleting}
        onConfirm={onDelete}
      />

      <ConfirmDialog
        open={disableConfirmOpen}
        onOpenChange={setDisableConfirmOpen}
        title="Disable this student's login?"
        description="They won't be able to sign in until you re-enable it. Their photos and history are kept — nothing is deleted."
        confirmLabel="Disable login"
        loading={statusSaving}
        onConfirm={() => onToggleStatus("disabled")}
      />

      <InviteResultDialog invite={invite} onClose={() => setInvite(null)} />
    </div>
  );
}
