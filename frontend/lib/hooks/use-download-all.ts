"use client";

import { downloadZip } from "client-zip";
import { useState } from "react";

import { downloadMedia, recordDownload } from "@/lib/api/endpoints";

interface ZipEntry {
  name: string;
  input: Blob;
}

/** Fetch each photo's blob (bounded concurrency, order-preserving); a photo that fails to
 *  fetch is skipped rather than failing the whole zip. */
async function fetchEntries(
  mediaIds: string[],
  onProgress: () => void,
): Promise<ZipEntry[]> {
  const results: (ZipEntry | null)[] = new Array(mediaIds.length).fill(null);
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
        const subtype = blob.type.split("/")[1];
        const ext = !subtype || subtype === "octet-stream" ? "jpg" : subtype;
        results[i] = { name: `photo-${String(i + 1).padStart(3, "0")}.${ext}`, input: blob };
        // A real download → audit it best-effort (BP8b), never blocking the zip.
        void recordDownload(mediaIds[i]).catch(() => {});
      } catch {
        results[i] = null; // skip this one; keep the rest
      } finally {
        onProgress();
      }
    }
  }

  const pool = Math.min(4, mediaIds.length);
  await Promise.all(Array.from({ length: pool }, worker));
  return results.filter((e): e is ZipEntry => e !== null);
}

/**
 * "Download all" for the student's own photos (BP3): mint each entitled signed URL, fetch
 * the bytes, and stream them into ONE `my-photos.zip` client-side (client-zip) — no server
 * change, no per-photo save dialogs. `done`/`total` drive a progress label; `onDownloadAll`
 * resolves with the number of photos actually saved (so the caller can flag a partial
 * result) and throws only if NOTHING could be fetched.
 *
 * NB (v1): the whole archive is buffered in memory before saving, fine for a student's own
 * modest set (tens of photos); a streaming save is the scale-up if galleries grow large.
 */
export function useDownloadAll(mediaIds: string[]) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(0);

  async function onDownloadAll(): Promise<number> {
    if (busy || mediaIds.length === 0) return 0;
    setBusy(true);
    setDone(0);
    try {
      const entries = await fetchEntries(mediaIds, () => setDone((d) => d + 1));
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
    } finally {
      setBusy(false);
    }
  }

  return { busy, done, total: mediaIds.length, onDownloadAll };
}
