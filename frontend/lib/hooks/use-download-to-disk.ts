"use client";

import { useState } from "react";
import { mutate } from "swr";

import { downloadToDisk } from "@/lib/api/download";
import { recordDownload } from "@/lib/api/endpoints";
import type { DownloadResponse } from "@/lib/api/types";
import { sanitizeFilename } from "@/lib/utils";

/**
 * Save one media to disk, with a `downloading` flag for the button and a new-tab fallback
 * if the blob fetch throws (decisions/0035). Shared by the Lightbox and the photo page.
 *
 * On the actual save it fires `recordDownload` (BP8b, decisions/0050) — best-effort, so a
 * failed/denied audit never blocks the download — which is what distinguishes a real
 * download from a mere view (both mint the same signed URL). Then it revalidates the
 * per-photo download-log so an open history panel updates live.
 *
 * BP20: `label` (e.g. the event + date) names the saved file when given — the student's save
 * keeps its story; omitted → the legacy `photo-{id}` base (staff surfaces).
 */
export function useDownloadToDisk(
  mediaId: string,
  download: DownloadResponse | undefined,
  label?: string,
) {
  const [downloading, setDownloading] = useState(false);

  async function onDownload() {
    if (!download) return;
    setDownloading(true);
    // Fire-and-forget: the audit must never delay or block the save.
    void recordDownload(mediaId)
      .then(() => mutate(`media/${mediaId}/download-log`))
      .catch(() => {});
    const base = (label && sanitizeFilename(label)) || `photo-${mediaId.slice(0, 8)}`;
    try {
      await downloadToDisk(download.download_url, base);
    } catch {
      window.open(download.download_url, "_blank", "noopener");
    } finally {
      setDownloading(false);
    }
  }

  return { downloading, onDownload };
}
