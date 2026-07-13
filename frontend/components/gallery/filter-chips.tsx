"use client";

import { cn } from "@/lib/utils";

export interface ChipItem {
  id: string;
  label: string;
  count: number;
}

/**
 * A single-select filter as a radiogroup (decisions/0035) — the correct semantics for
 * "pick one of N" (vs a bag of independent aria-pressed toggles). Used by the event
 * gallery's by-student view and the student detail's appears-in view.
 */
export function FilterChips({
  items,
  activeId,
  onSelect,
  ariaLabel,
}: {
  items: ChipItem[];
  activeId: string;
  onSelect: (id: string) => void;
  ariaLabel: string;
}) {
  return (
    <div role="radiogroup" aria-label={ariaLabel} className="flex flex-wrap gap-2">
      {items.map((item) => {
        const active = item.id === activeId;
        return (
          <button
            key={item.id}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onSelect(item.id)}
            className={cn(
              "flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-body-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              active
                ? "border-accent-hover bg-surface-2 text-ink"
                : "border-hairline text-ink-secondary hover:bg-surface",
            )}
          >
            {item.label}
            <span className="text-tabular tabular-nums text-ink-secondary">{item.count}</span>
          </button>
        );
      })}
    </div>
  );
}
