import { studentUploadUrl } from "./endpoints";
import { ApiError } from "./errors";

const FALLBACK_MAX_MB = 30;

/**
 * Upload a student reference photo straight to Supabase (decisions/0033): mint a
 * signed target via the BFF, validate type/size client-side, then PUT the bytes
 * DIRECTLY to the signed URL (never through the BFF/backend). Returns the object
 * path to submit with `createStudent`. Uses XHR for upload-progress events.
 */
export async function uploadReferencePhoto(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<string> {
  if (!file.type.startsWith("image/")) {
    throw new ApiError(400, "Please choose an image file.");
  }

  const { upload_url, object_path, max_upload_mb } = await studentUploadUrl();
  const maxMb = max_upload_mb || FALLBACK_MAX_MB;
  if (file.size > maxMb * 1024 * 1024) {
    throw new ApiError(400, `Image is too large (max ${maxMb} MB).`);
  }

  await putToSignedUrl(upload_url, file, onProgress);
  return object_path;
}

function putToSignedUrl(
  url: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.timeout = 120_000; // don't hang the dialog forever if the PUT stalls mid-stream
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
