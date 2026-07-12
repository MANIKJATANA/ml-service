/**
 * Fetch a (signed) URL's bytes and save them to disk with a filename. The signed URL is
 * cross-origin (Supabase), so an `<a download>` would just display the image — fetching
 * the blob and clicking an object URL forces a real "Save as" (decisions/0035). Callers
 * fall back to opening the URL in a new tab if this throws.
 */
export async function downloadToDisk(url: string, baseName: string): Promise<void> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`download failed: ${res.status}`);
  const blob = await res.blob();
  const subtype = blob.type.split("/")[1];
  const ext = !subtype || subtype === "octet-stream" ? "jpg" : subtype;
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = `${baseName}.${ext}`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Defer the revoke a tick — some engines abort the download if the object URL is revoked
  // in the same tick as the click, especially for large blobs.
  setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
}
