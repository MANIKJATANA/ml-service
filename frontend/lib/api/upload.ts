import { eventMediaUploadUrl, registerMedia, studentUploadUrl } from "./endpoints";
import { ApiError } from "./errors";
import type { MediaResponse, MediaType } from "./types";

const FALLBACK_MAX_MB = 30;

/**
 * Upload a student reference photo straight to Supabase (decisions/0033): mint a signed
 * target via the BFF, validate type/size client-side, then PUT the bytes DIRECTLY to the
 * signed URL (never through the BFF/backend). Returns the object path to submit with
 * `createStudent` / `setStudentReferencePhoto`. BP17: the backend generates the display
 * thumbnail from this object on create — the frontend uploads only the original.
 */
export async function uploadReferencePhoto(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<string> {
  assertImage(file);
  const { upload_url, object_path, max_upload_mb } = await studentUploadUrl();
  assertSize(file, max_upload_mb);
  await putToSignedUrl(upload_url, file, onProgress);
  return object_path;
}

/**
 * Upload one event photo or video (decisions/0034, BP6/0043): mint a per-event signed
 * target, PUT the bytes straight to Supabase, then register the object as a `media` row
 * carrying its detected type. Returns the created media. BP17: for an image the backend
 * generates the display thumbnail on register (video keeps its browser poster). Registering
 * enqueues nothing — processing is the separate event-level "Process" action.
 */
export async function uploadEventMedia(
  eventId: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<MediaResponse> {
  const mediaType = mediaTypeOf(file);
  const { upload_url, object_path, max_upload_mb } = await eventMediaUploadUrl(eventId);
  assertSize(file, max_upload_mb);
  await putToSignedUrl(upload_url, file, onProgress);
  // If register fails after the PUT, the object is orphaned in the bucket (no media row).
  // Accepted for v1 — the upload item is marked failed and a storage lifecycle policy reaps
  // unreferenced objects; the FE can't delete via an upload-only signed URL.
  return registerMedia(eventId, object_path, mediaType);
}

/** Classify a picked file as image or video by its MIME type, rejecting anything else. */
function mediaTypeOf(file: File): MediaType {
  if (file.type.startsWith("image/")) return "image";
  if (file.type.startsWith("video/")) return "video";
  throw new ApiError(400, "Please choose an image or video file.");
}

function assertImage(file: File): void {
  if (!file.type.startsWith("image/")) {
    throw new ApiError(400, "Please choose an image file.");
  }
}

function assertSize(file: File, maxUploadMb: number): void {
  const maxMb = maxUploadMb || FALLBACK_MAX_MB;
  if (file.size > maxMb * 1024 * 1024) {
    throw new ApiError(400, `File is too large (max ${maxMb} MB).`);
  }
}

function putToSignedUrl(
  url: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.timeout = 120_000; // don't hang forever if the PUT stalls mid-stream
    if (file.type) xhr.setRequestHeader("Content-Type", file.type);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(new ApiError(xhr.status || 502, "Upload failed. Please try again."));
      }
    };
    xhr.onerror = () => reject(new ApiError(502, "Upload failed. Please try again."));
    xhr.ontimeout = () => reject(new ApiError(504, "Upload timed out. Please try again."));
    xhr.send(file);
  });
}
