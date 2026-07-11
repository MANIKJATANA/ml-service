import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge class names conditionally (clsx) and de-duplicate conflicting Tailwind
 * utilities (tailwind-merge) — the standard `cn()` used across the UI kit.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
