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
  // BP19d: retain each file's handle by item id so a failed upload can be RE-tried without
  // re-picking it. File objects are cheap references (the bytes aren't held in memory until
  // read), and the map dies with the page, so retaining them for the session is fine.
  const filesById = useRef<Map<string, File>>(new Map());

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

  // Bounded pool: `worker`s share `idx`, each pulling the next entry until the batch drains.
  // idx++ is synchronous between awaits, so no two workers take the same file.
  function runPool(entries: { id: string; file: File }[]) {
    let idx = 0;
    const worker = async () => {
      while (idx < entries.length) {
        const { id, file } = entries[idx++];
        await uploadOne(id, file);
      }
    };
    void Promise.all(
      Array.from({ length: Math.min(UPLOAD_CONCURRENCY, entries.length) }, worker),
    );
  }

  function add(files: File[]) {
    if (files.length === 0) return;
    const batch = files.map((file) => {
      const id = String(nextId.current++);
      filesById.current.set(id, file);
      return { id, file };
    });
    setItems((prev) => [
      ...prev,
      ...batch.map(({ id, file }) => ({
        id,
        name: file.name,
        status: "queued" as const,
        progress: 0,
      })),
    ]);
    runPool(batch);
  }

  // BP19d: re-run just the failed items (using their retained file handles) so an
  // interrupted / flaky upload doesn't force the user to re-pick every file. Only offered
  // when the batch is idle (no overlapping pools), so no two workers race the same item.
  function retryFailed() {
    const entries: { id: string; file: File }[] = [];
    for (const it of items) {
      if (it.status !== "error") continue;
      // The map is append-only (set in `add`, never deleted), so this lookup is always a hit;
      // the guard is defensive — a miss would just leave that item in `error`, never wrongly done.
      const file = filesById.current.get(it.id);
      if (file !== undefined) entries.push({ id: it.id, file });
    }
    if (entries.length === 0) return;
    const retrying = new Set(entries.map((e) => e.id));
    setItems((prev) =>
      prev.map((it) =>
        retrying.has(it.id)
          ? { ...it, status: "queued" as const, progress: 0, error: undefined }
          : it,
      ),
    );
    runPool(entries);
  }

  return { items, isUploading, summary, add, retryFailed };
}
