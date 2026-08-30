"use client";

import { useEffect, useRef, useState } from "react";

import { deleteReferencePhotoUpload, setStudentReferencePhoto } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { EnrollmentStatus } from "@/lib/api/types";
import { uploadReferencePhoto } from "@/lib/api/upload";

const UPLOAD_CONCURRENCY = 3;

export type BulkEnrollStatus = "queued" | "uploading" | "enrolling" | "done" | "error";

/** One assigned photo to upload + enroll (BP10). `id` is a stable per-row id. */
export interface BulkEnrollInput {
  id: string;
  file: File;
  studentId: string;
  studentName: string;
  filename: string;
}

export interface BulkEnrollItem {
  id: string;
  filename: string;
  studentName: string;
  status: BulkEnrollStatus;
  progress: number; // 0–100
  enrollmentStatus?: EnrollmentStatus; // set when `done` (enrolled | failed)
  error?: string;
}

/**
 * Bulk reference-photo enrollment (BP10, decisions/0057). Only after the user confirms the
 * mapping, each assigned photo runs the same trusted path as the single "Add photo":
 * `uploadReferencePhoto` (mint → PUT straight to Supabase) → the existing per-student
 * `setStudentReferencePhoto` (attach + BP17 thumbnail + ML enroll). A bounded pool keeps at
 * most `UPLOAD_CONCURRENCY` in flight; per-item status/progress is tracked by a stable id and
 * a failure is isolated (never aborts the batch).
 *
 * If the PUT succeeds but the attach THROWS (student deleted mid-batch / transient), the
 * uploaded object is orphaned — so we best-effort `deleteReferencePhotoUpload` it (nothing left
 * in storage). A returned `enrollment_status: failed` is NOT an orphan: the photo IS attached
 * (the row keeps it, retryable), so the object stays.
 *
 * Holds no server cache — the caller revalidates the students/dashboard keys when done.
 */
export function useBulkPhotoEnroll() {
  const [items, setItems] = useState<BulkEnrollItem[]>([]);
  const mounted = useRef(true);
  // BP27c: retain each row's full enroll input (incl. its `File` handle) by item id so a failed
  // row can be RE-tried without re-picking. `run` (re)writes the current batch's inputs here before
  // the pool starts; row ids are the per-batch index, so a new batch OVERWRITES the same keys — and
  // `retryFailed` only looks up the CURRENT `items`, so it always resolves a live handle. File
  // objects are cheap references (the bytes aren't held until read), and the map dies with the page.
  const inputsById = useRef<Map<string, BulkEnrollInput>>(new Map());

  useEffect(() => {
    return () => {
      mounted.current = false;
    };
  }, []);

  const isRunning = items.some(
    (it) =>
      it.status === "queued" || it.status === "uploading" || it.status === "enrolling",
  );
  const summary = {
    total: items.length,
    done: items.filter((it) => it.status === "done" || it.status === "error").length,
    enrolled: items.filter(
      (it) => it.status === "done" && it.enrollmentStatus === "enrolled",
    ).length,
    failed: items.filter(
      (it) =>
        it.status === "error" ||
        (it.status === "done" && it.enrollmentStatus !== "enrolled"),
    ).length,
  };

  function patch(id: string, changes: Partial<BulkEnrollItem>) {
    if (!mounted.current) return; // an in-flight item may resolve after the dialog unmounts
    setItems((prev) => prev.map((it) => (it.id === id ? { ...it, ...changes } : it)));
  }

  async function runOne(input: BulkEnrollInput) {
    patch(input.id, { status: "uploading", progress: 0 });
    let objectPath: string;
    try {
      objectPath = await uploadReferencePhoto(input.file, (p) =>
        patch(input.id, { progress: p }),
      );
    } catch (err) {
      patch(input.id, {
        status: "error",
        error: isApiError(err) ? err.message : "Upload failed. Please try again.",
      });
      return;
    }
    patch(input.id, { status: "enrolling", progress: 100 });
    try {
      const student = await setStudentReferencePhoto(input.studentId, objectPath);
      patch(input.id, { status: "done", enrollmentStatus: student.enrollment_status });
    } catch (err) {
      // Uploaded but never attached — clean up the orphan (fire-and-forget; a cleanup failure
      // is harmless, the object is at worst reaped by the storage lifecycle policy).
      void deleteReferencePhotoUpload(objectPath).catch(() => {});
      patch(input.id, {
        status: "error",
        error: isApiError(err) ? err.message : "Enrollment failed. Please try again.",
      });
    }
  }

  // Bounded pool: `worker`s share `idx`, each pulling the next entry until the batch drains.
  // idx++ is synchronous between awaits, so no two workers take the same item. Reads from its
  // `entries` argument (NOT `items` state), so `run` and `retryFailed` reuse one implementation;
  // the two never overlap because the "Retry failed" button only mounts once the prior pool's
  // `Promise.all` has drained (its `!isRunning` gate).
  function runPool(entries: BulkEnrollInput[]) {
    let idx = 0;
    const worker = async () => {
      while (idx < entries.length) {
        await runOne(entries[idx++]);
      }
    };
    void Promise.all(
      Array.from({ length: Math.min(UPLOAD_CONCURRENCY, entries.length) }, worker),
    );
  }

  /** Start a fresh batch (replaces any prior run's items). */
  function run(inputs: BulkEnrollInput[]) {
    if (inputs.length === 0) return;
    for (const it of inputs) inputsById.current.set(it.id, it); // retain for a later retry
    setItems(
      inputs.map((it) => ({
        id: it.id,
        filename: it.filename,
        studentName: it.studentName,
        status: "queued" as const,
        progress: 0,
      })),
    );
    runPool(inputs);
  }

  // BP27c: re-run just the failed rows (using their retained inputs) so a flaky upload/enroll
  // doesn't force the user to re-pick every photo. "Failed" == `error` OR a `done` row whose
  // enrollment didn't succeed (matching `summary.failed`). Only offered when the batch is idle
  // (no overlapping pools), so no two workers race the same item.
  function retryFailed() {
    const entries: BulkEnrollInput[] = [];
    for (const it of items) {
      const isFailed =
        it.status === "error" ||
        (it.status === "done" && it.enrollmentStatus !== "enrolled");
      if (!isFailed) continue;
      // The map is append-only (set in `run`, never deleted), so this lookup is always a hit;
      // the guard is defensive — a miss would just leave that item as-is, never wrongly done.
      const input = inputsById.current.get(it.id);
      if (input !== undefined) entries.push(input);
    }
    if (entries.length === 0) return;
    if (!mounted.current) return;
    const retrying = new Set(entries.map((e) => e.id));
    setItems((prev) =>
      prev.map((it) =>
        retrying.has(it.id)
          ? {
              ...it,
              status: "queued" as const,
              progress: 0,
              error: undefined,
              // Clear the stale enroll-failed pill so the row re-enters the running set.
              enrollmentStatus: undefined,
            }
          : it,
      ),
    );
    runPool(entries);
  }

  return { items, isRunning, summary, run, retryFailed };
}
