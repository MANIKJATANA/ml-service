/**
 * A per-category color for the calendar pill + the list/detail badge (BP11b, decisions/0059).
 *
 * Categories are configurable per school, so the color is DERIVED deterministically from the
 * category id (a stable hash into a fixed pale-tint palette) rather than stored. The 6 default
 * categories land on distinct tints; a custom one gets an auto-assigned color (two customs could
 * collide — a visual aid, not identity).
 */

// BP25 (R3-S2-06): a NON-semantic hue set (violet/teal/fuchsia/cyan/indigo/slate) — distinct
// from the success/warning/error/info status tones, so a category never reads as a status.
const PALETTE = [
  "bg-cat-1-soft text-cat-1-ink",
  "bg-cat-2-soft text-cat-2-ink",
  "bg-cat-3-soft text-cat-3-ink",
  "bg-cat-4-soft text-cat-4-ink",
  "bg-cat-5-soft text-cat-5-ink",
  "bg-cat-6-soft text-cat-6-ink",
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
