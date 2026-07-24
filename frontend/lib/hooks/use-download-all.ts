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

function nameFor(index: number, contentType: string | null): string {
  const subtype = (contentType ?? "").split("/")[1]?.split(";")[0];
  const ext = !subtype || subtype === "octet-stream" ? "jpg" : subtype;
  return `photo-${String(index + 1).padStart(3, "0")}.${ext}`;
}

/** Stream each entitled photo straight into the zip → disk (bounded memory). Sequential (the
 *  zip pulls one entry at a time), so slower than the buffered pool but survives huge sets. */
async function streamToDisk(
  picker: ShowSaveFilePicker,
  mediaIds: string[],
  onProgress: () => void,
): Promise<number> {
  let handle: SaveFileHandle;
  try {
    handle = await picker({
      suggestedName: "my-photos.zip",
      types: [{ description: "Zip archive", accept: { "application/zip": [".zip"] } }],
    });
  } catch {
    return 0; // the user dismissed the save dialog — a silent no-op, not an error
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
        entry = { name: nameFor(i, res.headers.get("content-type")), input: res };
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
  return saved;
}

/** Fetch each photo's blob (bounded concurrency, order-preserving), then buffer them into one
 *  in-memory zip and save via an anchor. A photo that fails to fetch is skipped. */
async function bufferedSave(mediaIds: string[], onProgress: () => void): Promise<number> {
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
        results[i] = { name: nameFor(i, blob.type), input: blob };
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
  anchor.download = "my-photos.zip";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
  return entries.length;
}

/**
 * "Download all" for a student's own photos (BP3, streaming in BP9/decisions/0055): mint each
 * entitled signed URL, fetch the bytes, and write them into ONE `my-photos.zip` client-side
 * (client-zip) — no server change, no per-photo save dialogs.
 *
 * On Chromium/Edge the zip **streams to disk** via the File System Access API, so memory
 * stays bounded to the in-flight fetch and a 900-photo set survives. Elsewhere it falls back
 * to buffering the archive in memory, capped at {@link BUFFERED_CAP} so it can't OOM.
 *
 * `done`/`total` drive a progress label; `onDownloadAll` resolves with the number of photos
 * actually saved (so the caller can flag a partial result) and throws only if nothing could
 * be fetched. A cancelled save dialog resolves to 0 (a silent no-op).
 */
export function useDownloadAll(mediaIds: string[]) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(0);

  async function onDownloadAll(): Promise<number> {
    if (busy || mediaIds.length === 0) return 0;
    setBusy(true);
    setDone(0);
    try {
      const picker = savePicker();
      const bump = () => setDone((d) => d + 1);
      if (picker) return await streamToDisk(picker, mediaIds, bump);
      return await bufferedSave(mediaIds.slice(0, BUFFERED_CAP), bump);
    } finally {
      setBusy(false);
    }
  }

  return { busy, done, total: mediaIds.length, onDownloadAll };
}
