"use client";

import { cn } from "@/lib/utils";

/**
 * The teacher list "focus" control (BP11c, decisions/0060): a compact segmented switch between
 * "My classes" (the teacher's assigned classes) and "All". A convenience default, not a hard
 * boundary — a teacher can always view everything. Shown only for a teacher who has ≥1 class.
 * Styled to the app's rounded-pill filter language (matches `FilterChips`).
 */
export function FocusToggle({
  value,
  onChange,
}: {
  value: boolean; // true = My classes (focused); false = All
  onChange: (focused: boolean) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Focus"
      className="inline-flex items-center gap-0.5 rounded-full border border-hairline bg-surface p-0.5"
    >
      {(
        [
          { on: true, label: "My classes" },
          { on: false, label: "All" },
        ] as const
      ).map((opt) => {
        const active = value === opt.on;
        return (
          <button
            key={opt.label}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(opt.on)}
            className={cn(
              "rounded-full px-3 py-1 text-body-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              active
                ? "bg-canvas text-ink shadow-sm"
                : "text-ink-secondary hover:text-ink",
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
