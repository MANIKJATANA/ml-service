"use client";

import useSWR from "swr";

import { getDownloadLog, getMediaDownloadLog } from "@/lib/api/endpoints";
import type {
  DownloadLogPageResponse,
  MediaDownloadLogResponse,
} from "@/lib/api/types";

/** One photo's download history (BP8b). `enabled` gates the fetch off for non-admins —
 *  the endpoint is `audit:view` (school_admin only), so a teacher/student would 403. */
export function useMediaDownloadLog(mediaId: string, enabled: boolean) {
  const { data, error, isLoading } = useSWR<MediaDownloadLogResponse>(
    enabled && mediaId ? `media/${mediaId}/download-log` : null,
    () => getMediaDownloadLog(mediaId),
  );
  return { log: data, error, isLoading };
}

/** One page of the school-wide access log (BP8b; BP28a adds the actor-role + date-range
 *  filters). Keyed on the page params so paging / filtering refetches; `keepPreviousData`
 *  avoids a flash between pages. */
export function useDownloadLog(params: {
  limit: number;
  offset: number;
  eventId?: string;
  studentId?: string;
  actorRole?: string;
  createdFrom?: string;
  createdTo?: string;
}) {
  const { limit, offset, eventId, studentId, actorRole, createdFrom, createdTo } = params;
  const { data, error, isLoading, mutate } = useSWR<DownloadLogPageResponse>(
    `audit/downloads?limit=${limit}&offset=${offset}&event=${eventId ?? ""}` +
      `&student=${studentId ?? ""}&role=${actorRole ?? ""}` +
      `&from=${createdFrom ?? ""}&to=${createdTo ?? ""}`,
    () => getDownloadLog(params),
    { keepPreviousData: true },
  );
  return { page: data, error, isLoading, mutate };
}
