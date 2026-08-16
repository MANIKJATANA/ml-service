"use client";

import { Images } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { StudentPicker, type PickedStudent } from "@/components/students/student-picker";
import { Button } from "@/components/ui/button";
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
  const { items, isRunning, summary, run } = useBulkPhotoEnroll();
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
          ? { ...r, studentId: s.id, studentName: s.name, enrollmentStatus: s.enrollment_status }
          : r,
      ),
    );
  }

  function skip(rowId: string) {
    setRows((prev) =>
      prev.map((r) =>
        r.id === rowId
          ? { ...r, studentId: null, studentName: null, enrollmentStatus: null }
          : r,
      ),
    );
  }

  const assignedIds = new Set(
    rows.filter((r) => r.studentId).map((r) => r.studentId as string),
  );
  // Row count (what we actually upload) — equal to the distinct-student count while
  // double-assignment is blocked, but the honest number for the button + skip total.
  const assignedCount = rows.filter((r) => r.studentId).length;

  function disabledForRow(row: Row): Set<string> {
    // Every student assigned to a DIFFERENT photo (so its own row's "Change" isn't greyed).
    const s = new Set(assignedIds);
    if (row.studentId) s.delete(row.studentId);
    return s;
  }

  function start() {
    const inputs = rows
      .filter((r) => r.studentId)
      .map((r) => ({
        id: r.id,
        file: r.file,
        filename: r.filename,
        studentId: r.studentId as string,
        studentName: r.studentName ?? "",
      }));
    if (inputs.length === 0) {
      toast("Assign at least one photo to a student.", "error");
      return;
    }
    firedRef.current = false; // this batch hasn't refreshed the list yet
    setPhase("run");
    run(inputs);
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
            assignedCount={assignedCount}
            disabledForRow={disabledForRow}
            onAssign={assign}
            onSkip={skip}
            onReset={() => {
              setPhase("pick");
              setRows([]);
            }}
            onStart={start}
            container={portalContainer}
          />
        ) : (
          <RunStep items={items} isRunning={isRunning} summary={summary} />
        )}
      </DialogContent>
    </Dialog>
  );
}

function MapStep({
  rows,
  assignedCount,
  disabledForRow,
  onAssign,
  onSkip,
  onReset,
  onStart,
  container,
}: {
  rows: Row[];
  assignedCount: number;
  disabledForRow: (row: Row) => Set<string>;
  onAssign: (rowId: string, s: PickedStudent) => void;
  onSkip: (rowId: string) => void;
  onReset: () => void;
  onStart: () => void;
  container: HTMLElement | null;
}) {
  const skipped = rows.length - assignedCount;
  return (
    <div className="flex flex-col gap-4">
      <p role="status" className="text-body-sm text-ink-secondary">
        {assignedCount} of {rows.length} photo{rows.length === 1 ? "" : "s"} matched
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
                        <span className="text-body-sm text-ink-secondary">
                          Already enrolled — will replace
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
        <Button type="button" onClick={onStart} disabled={assignedCount === 0}>
          Upload {assignedCount} photo{assignedCount === 1 ? "" : "s"}
        </Button>
      </div>
    </div>
  );
}

function RunStep({
  items,
  isRunning,
  summary,
}: {
  items: BulkEnrollItem[];
  isRunning: boolean;
  summary: { total: number; done: number; enrolled: number; failed: number };
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
      <div className="mt-1 flex justify-end">
        <DialogClose asChild>
          <Button type="button" disabled={isRunning}>
            Done
          </Button>
        </DialogClose>
      </div>
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
