"use client";

import * as Popover from "@radix-ui/react-popover";
import { ListFilter } from "lucide-react";
import { useMemo, useState } from "react";

import { buttonVariants } from "@/components/ui/button";
import { SearchInput } from "@/components/ui/search-input";
import type { EventForStudentResponse } from "@/lib/api/types";
import { formatEventDate } from "@/lib/events/calendar";
import { cn } from "@/lib/utils";

/**
 * A searchable single-select event picker (decisions/0100) — modelled on BP10's `StudentPicker`,
 * but it filters the already-loaded events list CLIENT-side (a student appears in a bounded number
 * of events, so the whole list is in hand). Used on the student "Appears in" section so a long
 * event history (10–20+) is one search away, beyond the "All + latest few" quick chips. Newest
 * events first; picking one calls `onPick` and closes.
 */
export function EventPicker({
  events,
  activeId,
  onPick,
  triggerLabel = "Filter events",
  ariaLabel = "Filter events",
}: {
  events: EventForStudentResponse[];
  activeId?: string | null;
  onPick: (eventId: string) => void;
  triggerLabel?: string;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  // Newest-first (undated last), then a client-side name filter.
  const sorted = useMemo(
    () =>
      [...events].sort((a, b) => {
        if (a.event_date === b.event_date) return 0;
        if (a.event_date === null) return 1;
        if (b.event_date === null) return -1;
        return a.event_date < b.event_date ? 1 : -1;
      }),
    [events],
  );
  const q = query.trim().toLowerCase();
  const filtered = q ? sorted.filter((e) => e.name.toLowerCase().includes(q)) : sorted;

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
        // Reflect an active pick on the trigger (this picker, unlike StudentPicker, holds a
        // persistent selection) so the control that owns the list shows the current filter state.
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
            placeholder="Search events…"
            className="sm:max-w-none"
          />
          <ul className="max-h-56 overflow-y-auto overscroll-contain rounded-button border border-hairline">
            {filtered.length === 0 ? (
              <li className="px-2 py-2 text-body-sm text-ink-secondary">No events found.</li>
            ) : (
              filtered.map((e) => (
                <li key={e.event_id}>
                  <button
                    type="button"
                    aria-current={e.event_id === activeId ? "true" : undefined}
                    onClick={() => choose(e.event_id)}
                    className={cn(
                      "flex w-full items-center gap-2 px-2 py-1.5 text-left hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      e.event_id === activeId && "bg-surface-2",
                    )}
                  >
                    <span className="min-w-0 flex-1 truncate text-body-sm text-ink">{e.name}</span>
                    <span className="shrink-0 text-body-sm text-ink-secondary">
                      {formatEventDate(e.event_date)}
                    </span>
                    <span className="shrink-0 tabular-nums text-body-sm text-ink-secondary">
                      {e.media_count}
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
