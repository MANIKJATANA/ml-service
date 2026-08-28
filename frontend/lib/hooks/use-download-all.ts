"use client";

import { downloadZip } from "client-zip";
import { useState } from "react";

import { downloadMedia, recordDownload } from "@/lib/api/endpoints";

// Minimal File System Access API surface (not in the TS DOM lib) — used to STREAM the zip to
// disk on Chromium/Edge so memory stays bounded to the in-flight fetch, never the archive.
type SaveWritable = WritableStream<Uint8Array>;
interface SaveFileHandle {
  createWritable(): Promise<SaveWritable>;
}
type ShowSaveFilePicker = (options?: {
  suggestedName?: string;
  types?: { description?: string; accept: Record<string, string[]> }[];
}) => Promise<SaveFileHandle>;

function savePicker(): ShowSaveFilePicker | null {
  if (typeof window === "undefined") return null;
  const fn = (window as unknown as { showSaveFilePicker?: ShowSaveFilePicker })
    .showSaveFilePicker;
  return typeof fn === "function" ? fn : null;
}

// Fallback (Firefox/Safari, no streaming save): the whole archive is buffered in memory, so
// bound the count to keep it from OOM-ing. Typical own-photo sets are far under this; a
// larger set on a non-streaming browser downloads the first N (documented honest limit).
const BUFFERED_CAP = 500;

// Two precise shapes so client-zip's input union narrows: a streamed Response, or a buffered
// Blob (BufferLike). A union `Blob | Response` would match neither of its input variants.
type StreamEntry = { name: string; input: Response };
type BlobEntry = { name: string; input: Blob };

/** BP20: optional per-download naming so a student's save keeps its story.
 *  `entryBase(index)` → the zip-entry path WITHOUT extension (e.g. "Sports Day/2026-07-04-001");
 *  the extension is appended from the response content-type. `zipName` overrides the archive
 *  filename. Omit both → the legacy `photo-001.jpg` in `my-photos.zip` (staff callers). */
export interface DownloadAllOptions {
  entryBase?: (index: number) => string;
  zipName?: string;
}

/** The outcome of a "download all": how many were saved, whether the non-streaming fallback
 *  capped the set (so the caller can be honest about "the first N"), and — BP24 — whether the
 *  user dismissed the save dialog (so `saved: 0` from a cancel reads differently from
 *  `saved: 0` because every fetch failed). */
export interface DownloadAllResult {
  saved: number;
  capped: boolean;
  cancelled: boolean;
}

function nameFor(index: number, contentType: string | null, entryBase?: (i: number) => string): string {
  const subtype = (contentType ?? "").split("/")[1]?.split(";")[0];
  const ext = !subtype || subtype === "octet-stream" ? "jpg" : subtype;
  const base = entryBase?.(index) ?? `photo-${String(index + 1).padStart(3, "0")}`;
  return `${base}.${ext}`;
}

/** Stream each entitled photo straight into the zip → disk (bounded memory). Sequential (the
 *  zip pulls one entry at a time), so slower than the buffered pool but survives huge sets. */
async function streamToDisk(
  picker: ShowSaveFilePicker,
  mediaIds: string[],
  onProgress: () => void,
  opts?: DownloadAllOptions,
): Promise<{ saved: number; cancelled: boolean }> {
  let handle: SaveFileHandle;
  try {
    handle = await picker({
      suggestedName: opts?.zipName ?? "my-photos.zip",
      types: [{ description: "Zip archive", accept: { "application/zip": [".zip"] } }],
    });
  } catch {
    // BP24: the user dismissed the save dialog — a silent no-op, distinct from all-failed.
    return { saved: 0, cancelled: true };
  }
  const writable = await handle.createWritable();
  let saved = 0;

  async function* entries(): AsyncGenerator<StreamEntry> {
    for (let i = 0; i < mediaIds.length; i += 1) {
      let entry: StreamEntry | null = null;
      try {
        const { download_url } = await downloadMedia(mediaIds[i]);
        const res = await fetch(download_url);
        if (!res.ok || !res.body) throw new Error(`status ${res.status}`);
        entry = { name: nameFor(i, res.headers.get("content-type"), opts?.entryBase), input: res };
        void recordDownload(mediaIds[i]).catch(() => {});
        saved += 1;
      } catch {
        entry = null; // skip this one; keep the rest
      } finally {
        onProgress();
      }
      if (entry) yield entry;
    }
  }

  const stream = downloadZip(entries()).body;
  if (stream === null) throw new Error("no zip stream");
  await stream.pipeTo(writable); // pipeTo closes the file when the source is done
  return { saved, cancelled: false };
}

/** Fetch each photo's blob (bounded concurrency, order-preserving), then buffer them into one
 *  in-memory zip and save via an anchor. A photo that fails to fetch is skipped. */
async function bufferedSave(
  mediaIds: string[],
  onProgress: () => void,
  opts?: DownloadAllOptions,
): Promise<number> {
  const results: (BlobEntry | null)[] = new Array(mediaIds.length).fill(null);
  let next = 0;

  async function worker() {
    while (next < mediaIds.length) {
      const i = next;
      next += 1;
      try {
        const { download_url } = await downloadMedia(mediaIds[i]);
        const res = await fetch(download_url);
        if (!res.ok) throw new Error(`status ${res.status}`);
        const blob = await res.blob();
        results[i] = { name: nameFor(i, blob.type, opts?.entryBase), input: blob };
        void recordDownload(mediaIds[i]).catch(() => {});
      } catch {
        results[i] = null;
      } finally {
        onProgress();
      }
    }
  }

  const pool = Math.min(4, mediaIds.length);
  await Promise.all(Array.from({ length: pool }, worker));
  const entries = results.filter((e): e is BlobEntry => e !== null);
  if (entries.length === 0) throw new Error("no photos could be downloaded");
  const zipBlob = await downloadZip(entries).blob();
  const url = URL.createObjectURL(zipBlob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = opts?.zipName ?? "my-photos.zip";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
  return entries.length;
}

/**
 * "Download all" for a student's own photos (BP3, streaming in BP9/decisions/0055): mint each
 * entitled signed URL, fetch the bytes, and write them into ONE zip client-side (client-zip)
 * — no server change, no per-photo save dialogs.
 *
 * On Chromium/Edge the zip **streams to disk** via the File System Access API, so memory
 * stays bounded to the in-flight fetch and a 900-photo set survives. Elsewhere it falls back
 * to buffering the archive in memory, capped at {@link BUFFERED_CAP} so it can't OOM.
 *
 * `done`/`total` drive a progress label; `onDownloadAll` resolves with `{saved, capped,
 * cancelled}` — `capped` is true when the non-streaming fallback trimmed a >{@link BUFFERED_CAP}
 * set (so the caller can say "the first N"); `cancelled` is true when the user dismissed the
 * save dialog (BP24 — a silent no-op, `saved: 0`); and it throws only if nothing could be
 * fetched (the buffered all-failed path). BP20: pass `opts` to name the zip + its entries by
 * event/date (staff callers omit it → legacy naming).
 */
export function useDownloadAll(mediaIds: string[], opts?: DownloadAllOptions) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(0);

  async function onDownloadAll(): Promise<DownloadAllResult> {
    if (busy || mediaIds.length === 0) return { saved: 0, capped: false, cancelled: false };
    setBusy(true);
    setDone(0);
    try {
      const picker = savePicker();
      const bump = () => setDone((d) => d + 1);
      if (picker) {
        const { saved, cancelled } = await streamToDisk(picker, mediaIds, bump, opts);
        return { saved, capped: false, cancelled };
      }
      const capped = mediaIds.length > BUFFERED_CAP;
      const saved = await bufferedSave(mediaIds.slice(0, BUFFERED_CAP), bump, opts);
      return { saved, capped, cancelled: false };
    } finally {
      setBusy(false);
    }
  }

  return { busy, done, total: mediaIds.length, cap: BUFFERED_CAP, onDownloadAll };
}
