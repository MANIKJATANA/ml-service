"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import type { EventListItem } from "@/lib/api/types";
import { type MonthGrid, monthLabel, parseLocalDate, toISODate } from "@/lib/events/calendar";
import { categoryColor } from "@/lib/events/categories";
import { cn } from "@/lib/utils";

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MAX_PILLS = 3;
// Readable per-cell date for the screen-reader gridcell label ("Sat, Jul 4").
const DAY_FMT = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  month: "short",
  day: "numeric",
});

/**
 * A read-only month calendar (BP11b, decisions/0059). Controlled — the parent owns the month
 * and passes the already-built `grid` (so the fetch window and the rendered cells are the exact
 * same 42 days). Buckets events onto their LOCAL day (via the timezone-safe `parseLocalDate`);
 * undated events are dropped with a note. Each event is a category-colored `<Link>` pill; a busy
 * day caps at 3 + "+N more", and the gridcell's aria-label carries the full date + event count.
 */
export function MonthCalendar({
  grid,
  events,
  onPrev,
  onNext,
  onToday,
  loading = false,
}: {
  grid: MonthGrid;
  events: EventListItem[];
  onPrev: () => void;
  onNext: () => void;
  onToday: () => void;
  loading?: boolean;
}) {
  const byDay = new Map<string, EventListItem[]>();
  for (const ev of events) {
    if (!ev.event_date) continue; // undated → not placeable on a day
    const d = parseLocalDate(ev.event_date);
    if (!d) continue;
    const iso = toISODate(d);
    const existing = byDay.get(iso);
    if (existing) existing.push(ev);
    else byDay.set(iso, [ev]);
  }

  const label = monthLabel(grid.year, grid.month);
  const countInMonth = grid.weeks
    .flat()
    .reduce((n, cell) => (cell.inMonth ? n + (byDay.get(cell.iso)?.length ?? 0) : n), 0);
  const hasUndated = events.some((e) => !e.event_date);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" aria-label="Previous month" onClick={onPrev}>
            <ChevronLeft className="size-4" aria-hidden="true" />
          </Button>
          <h2 className="w-40 text-center text-headline text-ink">{label}</h2>
          <Button variant="secondary" size="sm" aria-label="Next month" onClick={onNext}>
            <ChevronRight className="size-4" aria-hidden="true" />
          </Button>
        </div>
        <Button variant="secondary" size="sm" onClick={onToday}>
          Today
        </Button>
      </div>

      {/* Screen-reader cue on month change / load (the grid itself is visual). */}
      <p role="status" aria-live="polite" className="sr-only">
        {loading ? "Loading events…" : `${countInMonth} events in ${label}`}
      </p>

      {/* BP25 (R3-S4-02): scroll horizontally on a narrow screen instead of crushing the 7 columns. */}
      <div className="overflow-x-auto rounded-card border border-hairline">
      <div
        role="grid"
        aria-label={`Events for ${label}`}
        className="min-w-[600px]"
      >
        <div role="row" className="grid grid-cols-7 border-b border-hairline bg-surface">
          {WEEKDAYS.map((d) => (
            <div
              key={d}
              role="columnheader"
              className="px-2 py-1.5 text-body-sm font-medium text-ink-secondary"
            >
              {d}
            </div>
          ))}
        </div>
        {grid.weeks.map((week) => (
          <div key={week[0].iso} role="row" className="grid grid-cols-7">
            {week.map((cell) => {
              const dayEvents = byDay.get(cell.iso) ?? [];
              const overflow = dayEvents.length - MAX_PILLS;
              const dayLabel = `${DAY_FMT.format(cell.date)}${
                dayEvents.length
                  ? `, ${dayEvents.length} event${dayEvents.length === 1 ? "" : "s"}`
                  : ""
              }`;
              return (
                <div
                  key={cell.iso}
                  role="gridcell"
                  aria-label={dayLabel}
                  aria-current={cell.isToday ? "date" : undefined}
                  className={cn(
                    "min-h-24 overflow-hidden border-b border-r border-hairline p-1",
                    !cell.inMonth && "bg-surface",
                  )}
                >
                  <span
                    className={cn(
                      "inline-flex size-6 items-center justify-center text-body-sm",
                      cell.isToday
                        ? "rounded-full bg-accent-hover font-semibold text-on-accent"
                        : cell.inMonth
                          ? "text-ink"
                          : "text-ink-secondary",
                    )}
                  >
                    {cell.date.getDate()}
                  </span>
                  <ul className="mt-0.5 flex flex-col gap-0.5">
                    {dayEvents.slice(0, MAX_PILLS).map((ev) => (
                      <li key={ev.id}>
                        <Link
                          href={`/events/${ev.id}`}
                          title={ev.name}
                          className={cn(
                            "block truncate rounded px-1 text-body-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                            ev.category_id
                              ? categoryColor(ev.category_id)
                              : "bg-surface-2 text-ink-secondary",
                          )}
                        >
                          {ev.name}
                        </Link>
                      </li>
                    ))}
                    {overflow > 0 ? (
                      <li className="px-1 text-body-sm text-ink-secondary">+{overflow} more</li>
                    ) : null}
                  </ul>
                </div>
              );
            })}
          </div>
        ))}
      </div>
      </div>

      {hasUndated ? (
        <p className="text-body-sm text-ink-secondary">
          Events without a date aren&apos;t shown here — see the List tab.
        </p>
      ) : null}
    </div>
  );
}
