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
