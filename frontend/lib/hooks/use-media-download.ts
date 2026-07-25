"use client";

import useSWR from "swr";

import { downloadMedia } from "@/lib/api/endpoints";
import type { DownloadResponse, PhotoSize } from "@/lib/api/types";

/**
 * Fetch the short-lived signed URL for one media, only when `enabled` (so photo tiles
 * fetch lazily as they scroll into view — decisions/0035). `mutate` re-mints on demand
 * (e.g. the browser image 403s because the URL expired mid-session).
 *
 * `size` (BP17) is part of the SWR key, so a tile's `thumb` and the lightbox's `full` are
 * SEPARATE cache entries — opening the lightbox never reuses the small thumbnail.
 */
export function useMediaDownload(
  mediaId: string,
  enabled: boolean,
  size: PhotoSize = "full",
) {
  const { data, error, isLoading, mutate } = useSWR<DownloadResponse>(
    enabled && mediaId ? `media/${mediaId}/download?size=${size}` : null,
    () => downloadMedia(mediaId, size),
  );
  return { download: data, error, isLoading, mutate };
}
