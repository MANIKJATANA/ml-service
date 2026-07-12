"use client";

import { useEffect, useRef, useState } from "react";

import { isApiError } from "@/lib/api/errors";
import { uploadEventMedia } from "@/lib/api/upload";

const UPLOAD_CONCURRENCY = 3;

export type UploadStatus = "queued" | "uploading" | "done" | "error";

export interface UploadItem {
  id: string;
  name: string;
  status: UploadStatus;
  progress: number; // 0–100
  error?: string;
}

/**
 * Client-side manager for the multi-file event-photo upload (decisions/0034). Each file
 * runs the mint→PUT→register flow (`uploadEventMedia`); a bounded pool keeps at most
 * `UPLOAD_CONCURRENCY` in flight, and per-file status/progress is tracked by a stable
 * local id. A failed file is isolated (marked `error`) and never aborts the batch — the
 * user can review failures and re-add them. Holds no server cache; the caller revalidates
 * the event's media/status keys when navigating back. Call `add` only when not
 * `isUploading` (the UI disables the picker) — a call during an active batch spawns a
 * second, independent pool.
 */
export function useMediaUpload(eventId: string) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const nextId = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    return () => {
      mounted.current = false;
    };
  }, []);

  const isUploading = items.some(
    (it) => it.status === "queued" || it.status === "uploading",
  );
  const summary = {
    total: items.length,
    done: items.filter((it) => it.status === "done").length,
    failed: items.filter((it) => it.status === "error").length,
  };

  function patch(id: string, changes: Partial<UploadItem>) {
    if (!mounted.current) return; // an in-flight upload may resolve after the user leaves
    setItems((prev) => prev.map((it) => (it.id === id ? { ...it, ...changes } : it)));
  }

  async function uploadOne(id: string, file: File) {
    patch(id, { status: "uploading", progress: 0 });
    try {
      await uploadEventMedia(eventId, file, (p) => patch(id, { progress: p }));
      patch(id, { status: "done", progress: 100 });
    } catch (err) {
      patch(id, {
        status: "error",
        error: isApiError(err) ? err.message : "Upload failed. Please try again.",
      });
    }
  }

  function add(files: File[]) {
    if (files.length === 0) return;
    const batch = files.map((file) => ({ id: String(nextId.current++), file }));
    setItems((prev) => [
      ...prev,
      ...batch.map(({ id, file }) => ({
        id,
        name: file.name,
        status: "queued" as const,
        progress: 0,
      })),
    ]);
    // Bounded pool: `worker`s share `idx`, each pulling the next file until the batch
    // drains. idx++ is synchronous between awaits, so no two workers take the same file.
    let idx = 0;
    const worker = async () => {
      while (idx < batch.length) {
        const { id, file } = batch[idx++];
        await uploadOne(id, file);
      }
    };
    void Promise.all(
      Array.from({ length: Math.min(UPLOAD_CONCURRENCY, batch.length) }, worker),
    );
  }

  return { items, isUploading, summary, add };
}
