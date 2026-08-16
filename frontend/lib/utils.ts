import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge class names conditionally (clsx) and de-duplicate conflicting Tailwind
 * utilities (tailwind-merge) — the standard `cn()` used across the UI kit.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Format an ISO timestamp as a short local date (e.g. "Jul 12, 2026"); "—" if invalid. */
export function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/** Format an ISO timestamp as a short local date + time (e.g. "Jul 12, 2026, 2:34 PM");
 *  "—" if invalid. Used where a bare date isn't precise enough (e.g. the download audit). */
export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Make a string safe to use as a file/folder name: drop path separators + reserved chars,
 *  collapse whitespace, trim, and cap the length. "" if nothing usable survives (BP20 — naming
 *  a student's saved photos/zip entries by event). */
export function sanitizeFilename(name: string): string {
  const cleaned = name
    .replace(/[\\/:*?"<>|]/g, "-") // path separators + Windows-reserved chars
    .replace(/\s+/g, " ") // collapse whitespace
    .replace(/-{2,}/g, "-") // collapse repeated dashes
    .trim()
    .replace(/^[.\-]+|[.\-]+$/g, ""); // no leading/trailing dot or dash
  return cleaned.slice(0, 80);
}

/** Copy text to the clipboard (BP7c — the shown-once temp password). Resolves `true` on
 *  success, `false` if the Clipboard API is unavailable (insecure context) or denied, so
 *  the caller can fall back to "select it manually". */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (!navigator.clipboard) return false;
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
