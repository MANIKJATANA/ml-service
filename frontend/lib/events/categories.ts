/**
 * A per-category color for the calendar pill + the list/detail badge (BP11b, decisions/0059).
 *
 * Categories are configurable per school, so the color is DERIVED deterministically from the
 * category id (a stable hash into a fixed pale-tint palette) rather than stored. The 6 default
 * categories land on distinct tints; a custom one gets an auto-assigned color (two customs could
 * collide — a visual aid, not identity). The palette uses the app's existing tone tokens.
 */

// Deliberately excludes the error/red tint — a normal category shouldn't read as an error.
const PALETTE = [
  "bg-info-soft text-info-strong",
  "bg-success-soft text-success-strong",
  "bg-warning-soft text-warning-strong",
  "bg-accent/10 text-accent-dark",
  "bg-surface-2 text-ink-secondary",
] as const;

function hashString(value: string): number {
  let h = 0;
  for (let i = 0; i < value.length; i += 1) {
    h = (h * 31 + value.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

/** A stable pale-tint class pair for a category, keyed on its id. */
export function categoryColor(id: string): string {
  return PALETTE[hashString(id) % PALETTE.length];
}
