"use client";

import useSWR from "swr";

import { downloadMedia } from "@/lib/api/endpoints";
import type { DownloadResponse } from "@/lib/api/types";

/**
 * Fetch the short-lived signed URL for one media, only when `enabled` (so photo tiles
 * fetch lazily as they scroll into view — decisions/0035). `mutate` re-mints on demand
 * (e.g. the browser image 403s because the URL expired mid-session).
 */
export function useMediaDownload(mediaId: string, enabled: boolean) {
  const { data, error, isLoading, mutate } = useSWR<DownloadResponse>(
    enabled && mediaId ? `media/${mediaId}/download` : null,
    () => downloadMedia(mediaId),
  );
  return { download: data, error, isLoading, mutate };
}
