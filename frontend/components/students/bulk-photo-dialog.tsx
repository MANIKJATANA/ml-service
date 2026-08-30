"use client";

import { Images, RotateCcw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { StudentPicker, type PickedStudent } from "@/components/students/student-picker";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { MultiFileDropzone } from "@/components/ui/multi-file-dropzone";
import { ProgressBar } from "@/components/ui/progress-bar";
import { StatusPill } from "@/components/ui/status-pill";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { matchPhotos } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { EnrollmentStatus } from "@/lib/api/types";
import { type BulkEnrollItem, useBulkPhotoEnroll } from "@/lib/hooks/use-bulk-photo-enroll";

// The FE per-batch limit for the pre-upload UX; the backend is the authoritative cap
// (BE_BULK_PHOTO_MAX_FILES → match-photos 422s an over-size batch). BP10, decisions/0057.
const MAX_PHOTOS = Number(process.env.NEXT_PUBLIC_BULK_PHOTO_MAX_FILES) || 50;

type Phase = "pick" | "map" | "run";

interface Row {
  id: string; // stable per-row id (also the enroll item id)
  file: File;
  filename: string;
  studentId: string | null;
  studentName: string | null;
  enrollmentStatus: EnrollmentStatus | null;
  // BP27c: for an already-enrolled match, whether to KEEP the current photo instead of
  // replacing it. Default false (= Replace, today's behavior). A kept row is never uploaded.
  keepExisting: boolean;
}

/**
 * Bulk reference-photo enrollment (BP10, decisions/0057). Drop a batch of photos named by
 * email → the backend auto-fills a mapping table (`matchPhotos`, filenames only) → the teacher
 * corrects any match, assigns unmatched photos, or leaves one unmatched to skip it → on confirm
 * ONLY the assigned photos upload (browser → Supabase) and enroll via the existing per-student
 * route. Nothing is uploaded during matching; an orphaned upload is cleaned up in the hook.
 */
export function BulkPhotoDialog({ onDone }: { onDone: () => void }) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<Phase>("pick");
  const [rows, setRows] = useState<Row[]>([]);
  const [matching, setMatching] = useState(false);
  // BP27c: guard a batch photo overwrite behind a confirm that names the count of enrolled
  // students whose face will be re-enrolled from the new photo (mirrors page.tsx's deleteConfirm).
  const [overwriteConfirm, setOverwriteConfirm] = useState(false);
  const { items, isRunning, summary, run, retryFailed } = useBulkPhotoEnroll();
  // The per-row picker's popover portals into THIS dialog's content node (captured by the ref
  // below) so its list scrolls — a body-portaled popover is blocked by the modal Dialog's
  // scroll-lock, and portaling here also escapes the map table's own overflow clip.
  const [portalContainer, setPortalContainer] = useState<HTMLElement | null>(null);

  // Refresh the list ONCE when a batch finishes — even if the dialog was closed mid-run (the
  // pool keeps running since this component stays mounted). `firedRef` resets when a run starts.
  // `onDoneRef` holds the latest callback (updated in an effect, never written during render).
  const onDoneRef = useRef(onDone);
  useEffect(() => {
    onDoneRef.current = onDone;
  }, [onDone]);
  const firedRef = useRef(false);
  useEffect(() => {
    if (!isRunning && items.length > 0 && !firedRef.current) {
      firedRef.current = true;
      onDoneRef.current();
    }
  }, [isRunning, items.length]);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    // Never reset mid-run (the pool keeps going in the background; reopening shows progress).
    if (!next && !isRunning) {
      setPhase("pick");
      setRows([]);
    }
  }

  async function onFiles(files: File[]) {
    const images = files.filter((f) => f.type.startsWith("image/"));
    if (images.length === 0) {
      toast("Please choose image files.", "error");
      return;
    }
    // De-dupe by filename (a picker can hand back the same file twice); keep the first.
    const seen = new Set<string>();
    const unique: File[] = [];
    for (const f of images) {
      if (!seen.has(f.name)) {
        seen.add(f.name);
        unique.push(f);
      }
    }
    const droppedDupes = images.length - unique.length;
    if (unique.length > MAX_PHOTOS) {
      toast(`Up to ${MAX_PHOTOS} photos at a time — please select fewer.`, "error");
      return;
    }
    setMatching(true);
    try {
      const res = await matchPhotos(unique.map((f) => f.name));
      const byName = new Map(res.results.map((r) => [r.filename, r]));
      // Build rows, de-duping repeated student matches (two files auto-mapping to the same
      // student): keep the first, leave the rest unmatched for the teacher to reassign/skip.
      const assigned = new Set<string>();
      const built: Row[] = unique.map((file, i) => {
        const m = byName.get(file.name);
        const matchedId = m?.matched ? m.student_id : null;
        const studentId = matchedId != null && !assigned.has(matchedId) ? matchedId : null;
        if (studentId) assigned.add(studentId);
        return {
          id: String(i),
          file,
          filename: file.name,
          studentId,
          studentName: studentId ? (m?.student_name ?? null) : null,
          enrollmentStatus: studentId ? (m?.enrollment_status ?? null) : null,
          keepExisting: false,
        };
      });
      setRows(built);
      setPhase("map");
      if (droppedDupes > 0) {
        toast(
          `Skipped ${droppedDupes} duplicate filename${droppedDupes === 1 ? "" : "s"}.`,
          "info",
        );
      }
    } catch (err) {
      toast(isApiError(err) ? err.message : "Couldn't match those photos.", "error");
    } finally {
      setMatching(false);
    }
  }

  function assign(rowId: string, s: PickedStudent) {
    setRows((prev) =>
      prev.map((r) =>
        r.id === rowId
          ? {
              ...r,
              studentId: s.id,
              studentName: s.name,
              enrollmentStatus: s.enrollment_status,
              keepExisting: false, // re-picking a student resets to Replace
            }
          : r,
      ),
    );
  }

  function skip(rowId: string) {
    setRows((prev) =>
      prev.map((r) =>
        r.id === rowId
          ? {
              ...r,
              studentId: null,
              studentName: null,
              enrollmentStatus: null,
              keepExisting: false,
            }
          : r,
      ),
    );
  }

  // BP27c: flip one already-enrolled row between Replace and Keep existing.
  function toggleKeep(rowId: string) {
    setRows((prev) =>
      prev.map((r) => (r.id === rowId ? { ...r, keepExisting: !r.keepExisting } : r)),
    );
  }

  const assignedIds = new Set(
    rows.filter((r) => r.studentId).map((r) => r.studentId as string),
  );
  // How many matched rows are set to KEEP their current photo (an enrolled row toggled off).
  const keptCount = rows.filter(
    (r) => r.studentId && r.enrollmentStatus === "enrolled" && r.keepExisting,
  ).length;
  // BP27c: a kept row is NOT uploaded — the "keep-existing = FE doesn't send the row" mechanism.
  // `effectiveCount` is what we actually upload (matched minus kept); `effectiveReplacing` is the
  // subset of those that overwrite an already-enrolled photo (the batch-overwrite confirm's count).
  const isKept = (r: Row) =>
    r.enrollmentStatus === "enrolled" && r.keepExisting;
  const uploadRows = rows.filter((r) => r.studentId && !isKept(r));
  const effectiveCount = uploadRows.length;
  const effectiveReplacing = uploadRows.filter(
    (r) => r.enrollmentStatus === "enrolled",
  ).length;

  function disabledForRow(row: Row): Set<string> {
    // Every student assigned to a DIFFERENT photo (so its own row's "Change" isn't greyed).
    const s = new Set(assignedIds);
    if (row.studentId) s.delete(row.studentId);
    return s;
  }

  /** Kick off the upload+enroll pool over the non-kept assigned rows. Assumes `effectiveCount > 0`
   *  (guarded by the callers). */
  function runEnroll() {
    const inputs = uploadRows.map((r) => ({
      id: r.id,
      file: r.file,
      filename: r.filename,
      studentId: r.studentId as string,
      studentName: r.studentName ?? "",
    }));
    firedRef.current = false; // this batch hasn't refreshed the list yet
    setPhase("run");
    run(inputs);
  }

  function start() {
    if (effectiveCount === 0) {
      toast(
        keptCount > 0
          ? "Every matched photo is set to keep the current one — nothing to upload."
          : "Assign at least one photo to a student.",
        "error",
      );
      return;
    }
    // BP27c: overwriting an already-enrolled student's photo is destructive-ish (re-enrolls their
    // face) — confirm it, naming the count. A pure-new batch (no enrolled replacements) runs directly.
    if (effectiveReplacing >= 1) {
      setOverwriteConfirm(true);
      return;
    }
    runEnroll();
  }

  // BP27c: parent-owned retry handler — reset the one-shot list-refresh guard (it lives in the
  // dialog, NOT the hook, mirroring `start`) so a retry batch also refreshes the list on finish.
  function handleRetry() {
    firedRef.current = false;
    retryFailed();
  }

  return (
    // Non-modal: a modal Dialog's scroll-lock (react-remove-scroll) blocks wheel/trackpad
    // scrolling on the per-row picker's popover list. Non-modal removes the lock so the list
    // scrolls by wheel + trackpad (not just the scrollbar); Esc + click-outside still close.
    // Trade-off (accepted): focus isn't trapped in the dialog.
    <Dialog open={open} onOpenChange={handleOpenChange} modal={false}>
      <DialogTrigger asChild>
        <Button variant="secondary">
          <Images className="size-4" aria-hidden="true" />
          Bulk photos
        </Button>
      </DialogTrigger>
      <DialogContent
        title="Bulk photo enrollment"
        description="Drop photos named by student email (e.g. aisha@school.edu.jpg). We match each to a student — correct any, assign the rest — then upload and enroll them all."
        className="max-w-2xl"
      >
        <div ref={setPortalContainer} />
        {phase === "pick" ? (
          <div className="flex flex-col gap-4">
            <p className="text-body-sm text-ink-secondary">
              Name each photo by the student&apos;s email — up to {MAX_PHOTOS} at a time. Nothing
              uploads until you review the matches on the next step.
            </p>
            <MultiFileDropzone
              onFiles={onFiles}
              disabled={matching}
              label="Photos"
              hint={matching ? "Matching…" : "Images only."}
            />
          </div>
        ) : phase === "map" ? (
          <MapStep
            rows={rows}
            effectiveCount={effectiveCount}
            keptCount={keptCount}
            disabledForRow={disabledForRow}
            onAssign={assign}
            onSkip={skip}
            onToggleKeep={toggleKeep}
            onReset={() => {
              setPhase("pick");
              setRows([]);
            }}
            onStart={start}
            container={portalContainer}
          />
        ) : (
          <RunStep
            items={items}
            isRunning={isRunning}
            summary={summary}
            onRetry={handleRetry}
          />
        )}
      </DialogContent>
      {/* BP27c: the batch-overwrite confirm — names the count of already-enrolled students whose
          face will be re-enrolled from the new photo. */}
      <ConfirmDialog
        open={overwriteConfirm}
        onOpenChange={setOverwriteConfirm}
        title="Replace existing photos?"
        description={`Replace the reference photo for ${effectiveReplacing} already-enrolled student${
          effectiveReplacing === 1 ? "" : "s"
        }? Their face will be re-enrolled from the new photo.`}
        confirmLabel="Replace and upload"
        onConfirm={() => {
          setOverwriteConfirm(false);
          runEnroll();
        }}
      />
    </Dialog>
  );
}

function MapStep({
  rows,
  effectiveCount,
  keptCount,
  disabledForRow,
  onAssign,
  onSkip,
  onToggleKeep,
  onReset,
  onStart,
  container,
}: {
  rows: Row[];
  effectiveCount: number;
  keptCount: number;
  disabledForRow: (row: Row) => Set<string>;
  onAssign: (rowId: string, s: PickedStudent) => void;
  onSkip: (rowId: string) => void;
  onToggleKeep: (rowId: string) => void;
  onReset: () => void;
  onStart: () => void;
  container: HTMLElement | null;
}) {
  const matched = rows.filter((r) => r.studentId).length;
  const skipped = rows.length - matched;
  return (
    <div className="flex flex-col gap-4">
      <p role="status" className="text-body-sm text-ink-secondary">
        {matched} of {rows.length} photo{rows.length === 1 ? "" : "s"} matched
        {keptCount > 0 ? ` · ${keptCount} kept (won't upload)` : ""}
        {skipped > 0 ? ` · ${skipped} unmatched (will be skipped)` : ""}.
      </p>
      <div className="max-h-96 overflow-y-auto rounded-card border border-hairline">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Photo</TableHead>
              <TableHead>Maps to</TableHead>
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell className="max-w-[12rem] truncate text-ink-secondary" title={r.filename}>
                  {r.filename}
                </TableCell>
                <TableCell>
                  {r.studentId ? (
                    <div className="flex flex-col gap-0.5">
                      <span className="font-medium text-ink">{r.studentName}</span>
                      {r.enrollmentStatus === "enrolled" ? (
                        // BP27c: an already-enrolled match can Replace (default) or Keep its
                        // current photo. A kept row is excluded from the upload.
                        <div
                          role="radiogroup"
                          aria-label={`Existing photo for ${r.studentName}`}
                          className="flex items-center gap-3 text-body-sm"
                        >
                          <label className="flex cursor-pointer items-center gap-1 text-ink-secondary">
                            <input
                              type="radio"
                              name={`keep-${r.id}`}
                              checked={!r.keepExisting}
                              onChange={() => {
                                if (r.keepExisting) onToggleKeep(r.id);
                              }}
                              className="size-4 text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
                            />
                            Replace
                          </label>
                          <label className="flex cursor-pointer items-center gap-1 text-ink-secondary">
                            <input
                              type="radio"
                              name={`keep-${r.id}`}
                              checked={r.keepExisting}
                              onChange={() => {
                                if (!r.keepExisting) onToggleKeep(r.id);
                              }}
                              className="size-4 text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
                            />
                            Keep existing
                          </label>
                        </div>
                      ) : null}
                      {r.enrollmentStatus === "enrolled" && r.keepExisting ? (
                        <span className="text-body-sm text-ink-secondary">
                          Will keep current photo
                        </span>
                      ) : null}
                    </div>
                  ) : (
                    <span className="text-body-sm text-ink-secondary">No match — will be skipped</span>
                  )}
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-2">
                    <StudentPicker
                      triggerLabel={r.studentId ? "Change" : "Assign"}
                      ariaLabel={
                        r.studentId
                          ? `Change the student for ${r.filename}`
                          : `Assign a student to ${r.filename}`
                      }
                      disabledIds={disabledForRow(r)}
                      onPick={(s) => onAssign(r.id, s)}
                      container={container}
                    />
                    {r.studentId ? (
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => onSkip(r.id)}
                        aria-label={`Skip ${r.filename}`}
                      >
                        Skip
                      </Button>
                    ) : null}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <div className="mt-1 flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onReset}>
          Choose different photos
        </Button>
        <Button type="button" onClick={onStart} disabled={effectiveCount === 0}>
          Upload {effectiveCount} photo{effectiveCount === 1 ? "" : "s"}
        </Button>
      </div>
    </div>
  );
}

function RunStep({
  items,
  isRunning,
  summary,
  onRetry,
}: {
  items: BulkEnrollItem[];
  isRunning: boolean;
  summary: { total: number; done: number; enrolled: number; failed: number };
  onRetry: () => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      {/* Visual progress — NOT a live region (would re-announce on every one of N items). */}
      <p className="text-body-sm text-ink-secondary">
        {isRunning
          ? `Uploading and enrolling… ${summary.done} of ${summary.total} done.`
          : `Done — ${summary.enrolled} enrolled${summary.failed > 0 ? `, ${summary.failed} failed` : ""}.`}
      </p>
      {/* Announced once, only when the batch finishes. */}
      <p role="status" aria-live="polite" className="sr-only">
        {!isRunning && summary.total > 0
          ? `Bulk enrollment complete. ${summary.enrolled} enrolled, ${summary.failed} failed.`
          : ""}
      </p>
      <div className="max-h-72 overflow-y-auto rounded-card border border-hairline">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Photo</TableHead>
              <TableHead>Student</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((it) => (
              <TableRow key={it.id}>
                <TableCell
                  className="max-w-[10rem] truncate text-ink-secondary"
                  title={it.filename}
                >
                  {it.filename}
                </TableCell>
                <TableCell className="text-ink">{it.studentName}</TableCell>
                <TableCell>
                  <ItemStatus item={it} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <div className="mt-1 flex justify-end gap-2">
        {/* BP27c: re-run just the failed rows through the same pool. The `!isRunning` guard is the
            single-pool invariant — never spawn an overlapping pool. A `no_face` failure won't
            self-heal on retry — the copy steers to replacing the photo. */}
        {!isRunning && summary.failed > 0 ? (
          <Button type="button" variant="secondary" onClick={onRetry}>
            <RotateCcw className="size-4" aria-hidden="true" />
            Retry failed ({summary.failed})
          </Button>
        ) : null}
        <DialogClose asChild>
          <Button type="button" disabled={isRunning}>
            Done
          </Button>
        </DialogClose>
      </div>
      {!isRunning && summary.failed > 0 ? (
        <p className="text-body-sm text-ink-secondary">
          A photo with no clear face won&apos;t change on retry — replace the photo instead.
        </p>
      ) : null}
    </div>
  );
}

function ItemStatus({ item }: { item: BulkEnrollItem }) {
  if (item.status === "queued") {
    return <span className="text-body-sm text-ink-secondary">Waiting…</span>;
  }
  if (item.status === "uploading") {
    return (
      <div className="w-28">
        <ProgressBar value={item.progress} label="Upload progress" />
      </div>
    );
  }
  if (item.status === "enrolling") {
    return <span className="text-body-sm text-ink-secondary">Enrolling…</span>;
  }
  if (item.status === "error") {
    return (
      <div className="flex flex-col gap-0.5">
        <StatusPill tone="error">Failed</StatusPill>
        {item.error ? <span className="text-body-sm text-ink-secondary">{item.error}</span> : null}
      </div>
    );
  }
  // done
  return item.enrollmentStatus === "enrolled" ? (
    <StatusPill tone="success">Enrolled</StatusPill>
  ) : (
    <StatusPill tone="warning">Enroll failed</StatusPill>
  );
}
