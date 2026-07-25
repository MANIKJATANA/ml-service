"use client";

import useSWR from "swr";

import { studentReferencePhoto } from "@/lib/api/endpoints";
import type { DownloadResponse, PhotoSize } from "@/lib/api/types";

/**
 * A signed URL for a student's reference photo — the staff-list/detail avatar (BP17).
 *
 * `enabled` gates the fetch off for photoless rows (the caller passes
 * `reference_photo_path !== null`), so the server-paginated list never fires N pointless
 * 404s. `shouldRetryOnError:false` keeps a photoless 404 from retry-spinning. Returns
 * `undefined` on no-photo/error → the avatar falls back to initials.
 */
export function useStudentReferencePhoto(
  studentId: string,
  enabled = true,
  size: PhotoSize = "thumb",
) {
  const { data } = useSWR<DownloadResponse>(
    enabled && studentId ? `students/${studentId}/reference-photo?size=${size}` : null,
    () => studentReferencePhoto(studentId, size),
    { shouldRetryOnError: false },
  );
  return { photoUrl: data?.download_url };
}
