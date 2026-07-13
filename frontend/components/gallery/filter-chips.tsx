"use client";

import { type KeyboardEvent, useRef } from "react";

import { cn } from "@/lib/utils";

export interface ChipItem {
  id: string;
  label: string;
  count: number;
}

/**
 * A single-select filter as a radiogroup (decisions/0035) — the correct semantics for
 * "pick one of N". Roving tabindex + arrow-key navigation per WAI-ARIA (decisions/0037):
 * the group is one tab stop (the checked chip), and ←/→/↑/↓ move + select.
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
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = -1;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      next = (index + 1) % items.length;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      next = (index - 1 + items.length) % items.length;
    }
    if (next < 0) return;
    event.preventDefault();
    onSelect(items[next].id);
    refs.current[next]?.focus();
  }

  return (
    <div role="radiogroup" aria-label={ariaLabel} className="flex flex-wrap gap-2">
      {items.map((item, index) => {
        const active = item.id === activeId;
        return (
          <button
            key={item.id}
            ref={(el) => {
              refs.current[index] = el;
            }}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onSelect(item.id)}
            onKeyDown={(e) => onKeyDown(e, index)}
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
