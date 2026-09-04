"use client";

import * as Popover from "@radix-ui/react-popover";
import { ListFilter } from "lucide-react";
import { useMemo, useState } from "react";

import { buttonVariants } from "@/components/ui/button";
import { SearchInput } from "@/components/ui/search-input";
import type { StudentInEventResponse } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * A searchable single-select student picker for the event gallery's "By student" tab — modelled on
 * `EventPicker` (client-side filter over an already-loaded list), NOT the server-hitting BP10
 * `StudentPicker`. An event's matched roster is fully in hand (`useEventStudents`), so a big event
 * (40–80 matched students) is one search away, beyond the "top few" quick chips. Sorted by
 * photo-count (most first); picking one calls `onPick` and closes.
 */
export function StudentChipPicker({
  students,
  activeId,
  onPick,
  triggerLabel = "Find student",
  ariaLabel = "Find student",
}: {
  students: StudentInEventResponse[];
  activeId?: string | null;
  onPick: (studentId: string) => void;
  triggerLabel?: string;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  // Most-matched first (stable), then a client-side name filter.
  const sorted = useMemo(
    () => [...students].sort((a, b) => b.media_count - a.media_count),
    [students],
  );
  const q = query.trim().toLowerCase();
  const filtered = q ? sorted.filter((s) => s.name.toLowerCase().includes(q)) : sorted;

  function choose(id: string) {
    onPick(id);
    setOpen(false);
    setQuery("");
  }

  return (
    <Popover.Root
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) setQuery("");
      }}
    >
      <Popover.Trigger
        aria-label={ariaLabel}
        // Reflect an active pick on the trigger so the control that owns the list shows the
        // current filter state (mirrors EventPicker).
        className={cn(
          buttonVariants({ variant: "secondary", size: "sm" }),
          activeId != null && "border-accent-hover text-ink",
        )}
      >
        <ListFilter className="size-4" aria-hidden="true" />
        {triggerLabel}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={6}
          collisionPadding={12}
          className="z-[60] flex w-72 flex-col gap-2 rounded-card border border-hairline bg-canvas p-3 shadow-lg focus-visible:outline-none"
        >
          <SearchInput
            value={query}
            onChange={setQuery}
            placeholder="Search students…"
            className="sm:max-w-none"
          />
          <ul className="max-h-56 overflow-y-auto overscroll-contain rounded-button border border-hairline">
            {filtered.length === 0 ? (
              <li className="px-2 py-2 text-body-sm text-ink-secondary">No students found.</li>
            ) : (
              filtered.map((s) => (
                <li key={s.student_id}>
                  <button
                    type="button"
                    aria-current={s.student_id === activeId ? "true" : undefined}
                    onClick={() => choose(s.student_id)}
                    className={cn(
                      "flex w-full items-center gap-2 px-2 py-1.5 text-left hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      s.student_id === activeId && "bg-surface-2",
                    )}
                  >
                    <span className="min-w-0 flex-1 truncate text-body-sm text-ink">{s.name}</span>
                    <span className="shrink-0 tabular-nums text-body-sm text-ink-secondary">
                      {s.media_count}
                    </span>
                  </button>
                </li>
              ))
            )}
          </ul>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
