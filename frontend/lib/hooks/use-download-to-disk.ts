"use client";

import { useState } from "react";

import { downloadToDisk } from "@/lib/api/download";
import type { DownloadResponse } from "@/lib/api/types";

/**
 * Save one media to disk, with a `downloading` flag for the button and a new-tab fallback
 * if the blob fetch throws (decisions/0035). Shared by the Lightbox and the photo page.
 */
export function useDownloadToDisk(mediaId: string, download: DownloadResponse | undefined) {
  const [downloading, setDownloading] = useState(false);

  async function onDownload() {
    if (!download) return;
    setDownloading(true);
    try {
      await downloadToDisk(download.download_url, `photo-${mediaId.slice(0, 8)}`);
    } catch {
      window.open(download.download_url, "_blank", "noopener");
    } finally {
      setDownloading(false);
    }
  }

  return { downloading, onDownload };
}
