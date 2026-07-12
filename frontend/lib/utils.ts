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
