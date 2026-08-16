/**
 * Pure, timezone-safe date helpers for the month calendar (BP11b, decisions/0059).
 *
 * THE TRAP: `new Date("2026-07-04")` parses as UTC midnight, so `.getDate()` returns July 3rd
 * in any timezone west of UTC — an off-by-one-day. Everything here parses a "YYYY-MM-DD" string
 * into a LOCAL calendar day by hand and never round-trips through `new Date(iso)` / `toISOString()`.
 * Kept isolated so the day-placement is easy to reason about (and unit-test if a runner is added).
 */

/** Parse "YYYY-MM-DD" as a LOCAL calendar day. Returns null if malformed. */
export function parseLocalDate(iso: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "YYYY-MM-DD" from a LOCAL Date (never `toISOString`, which would UTC-shift). */
export function toISODate(d: Date): string {
  const y = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${mo}-${day}`;
}

/** Friendly local date from a "YYYY-MM-DD" event date (timezone-safe via {@link parseLocalDate});
 *  "" for null/malformed. Used for the student photo "story" (BP20). */
export function formatEventDate(iso: string | null): string {
  const d = iso ? parseLocalDate(iso) : null;
  return d
    ? d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
    : "";
}

/** The local calendar year of a "YYYY-MM-DD" event date, or null (used to group the student
 *  event filter by year, BP20). */
export function eventYear(iso: string | null): number | null {
  const d = iso ? parseLocalDate(iso) : null;
  return d ? d.getFullYear() : null;
}

export interface DayCell {
  date: Date;
  iso: string;
  inMonth: boolean;
  isToday: boolean;
}

export interface MonthGrid {
  year: number;
  month: number; // 0-11
  weeks: DayCell[][]; // fixed 6 rows × 7 days
  gridStart: string; // "YYYY-MM-DD" of the first cell
  gridEnd: string; // "YYYY-MM-DD" of the last cell
}

/** A Sunday-started, fixed 6-row (42-cell) grid for (year, month). The fixed height avoids the
 *  layout jumping between 4/5/6-week months; spillover days carry `inMonth: false`. */
export function buildMonthGrid(
  year: number,
  month: number,
  today: Date = new Date(),
): MonthGrid {
  const first = new Date(year, month, 1);
  const start = new Date(year, month, 1 - first.getDay()); // back up to the grid's Sunday
  const todayIso = toISODate(today);
  const weeks: DayCell[][] = [];
  const cursor = new Date(start);
  for (let w = 0; w < 6; w += 1) {
    const row: DayCell[] = [];
    for (let d = 0; d < 7; d += 1) {
      const cell = new Date(cursor);
      const iso = toISODate(cell);
      row.push({
        date: cell,
        iso,
        inMonth: cell.getMonth() === month,
        isToday: iso === todayIso,
      });
      cursor.setDate(cursor.getDate() + 1); // JS-normalized (DST-safe)
    }
    weeks.push(row);
  }
  return { year, month, weeks, gridStart: weeks[0][0].iso, gridEnd: weeks[5][6].iso };
}

const MONTH_FMT = new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" });

/** "July 2026" for the calendar header. */
export function monthLabel(year: number, month: number): string {
  return MONTH_FMT.format(new Date(year, month, 1));
}

/** Shift a (year, month) by ±delta with carry. */
export function shiftMonth(
  year: number,
  month: number,
  delta: number,
): { year: number; month: number } {
  const d = new Date(year, month + delta, 1);
  return { year: d.getFullYear(), month: d.getMonth() };
}

/** The current (year, month) — for a page's initial calendar state. */
export function currentMonth(): { year: number; month: number } {
  const n = new Date();
  return { year: n.getFullYear(), month: n.getMonth() };
}
