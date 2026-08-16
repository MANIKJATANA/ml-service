"use client";

import { useMemo } from "react";

import { FilterChips } from "@/components/gallery/filter-chips";
import type { EventForStudentResponse } from "@/lib/api/types";
import { eventYear } from "@/lib/events/calendar";

// Beyond this many events, a flat chip row becomes a wall on a phone (R3-A4-03) — switch to a
// compact year-grouped select (newest year first, "All events" default).
const CHIP_LIMIT = 8;

interface YearGroup {
  key: string;
  label: string;
  events: EventForStudentResponse[];
}

/** Group events (already newest-first) by their event_date year, preserving order; undated
 *  events fall into a trailing "Other" group. */
function groupByYear(events: EventForStudentResponse[]): YearGroup[] {
  const groups: YearGroup[] = [];
  const byKey = new Map<string, YearGroup>();
  for (const e of events) {
    const y = eventYear(e.event_date);
    const key = y === null ? "other" : String(y);
    let group = byKey.get(key);
    if (!group) {
      group = { key, label: y === null ? "Other" : String(y), events: [] };
      byKey.set(key, group);
      groups.push(group);
    }
    group.events.push(e);
  }
  // Move the undated group to the end (stable sort keeps the year groups newest-first).
  groups.sort((a, b) => (a.key === "other" ? 1 : b.key === "other" ? -1 : 0));
  return groups;
}

/**
 * The student's event filter (BP20). A handful of events render as chips (newest-first); a
 * long history collapses into a year-grouped native select — accessible, compact, and it
 * never fills a phone screen with pills instead of photos.
 */
export function EventFilter({
  events,
  totalPhotos,
  activeId,
  onSelect,
}: {
  events: EventForStudentResponse[];
  totalPhotos: number;
  activeId: string;
  onSelect: (id: string) => void;
}) {
  const groups = useMemo(() => groupByYear(events), [events]);

  if (events.length <= CHIP_LIMIT) {
    return (
      <FilterChips
        ariaLabel="Events"
        activeId={activeId}
        onSelect={onSelect}
        items={[
          { id: "", label: "All events", count: totalPhotos },
          ...events.map((e) => ({ id: e.event_id, label: e.name, count: e.media_count })),
        ]}
      />
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor="event-filter" className="sr-only">
        Filter by event
      </label>
      <select
        id="event-filter"
        value={activeId}
        onChange={(e) => onSelect(e.target.value)}
        className="w-full rounded-button border border-hairline bg-canvas px-3 py-2 text-body text-ink transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:max-w-xs"
      >
        <option value="">All events ({totalPhotos})</option>
        {groups.map((group) => (
          <optgroup key={group.key} label={group.label}>
            {group.events.map((e) => (
              <option key={e.event_id} value={e.event_id}>
                {e.name}
                {e.media_count ? ` (${e.media_count})` : ""}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
}
