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

  /** Start a fresh batch (replaces any prior run's items). */
  function run(inputs: BulkEnrollInput[]) {
    if (inputs.length === 0) return;
    setItems(
      inputs.map((it) => ({
        id: it.id,
        filename: it.filename,
        studentName: it.studentName,
        status: "queued" as const,
        progress: 0,
      })),
    );
    // Bounded pool: workers share `idx`, each pulling the next input until the batch drains.
    // idx++ is synchronous between awaits, so no two workers take the same item.
    let idx = 0;
    const worker = async () => {
      while (idx < inputs.length) {
        await runOne(inputs[idx++]);
      }
    };
    void Promise.all(
      Array.from({ length: Math.min(UPLOAD_CONCURRENCY, inputs.length) }, worker),
    );
  }

  return { items, isRunning, summary, run };
}
