import type { MonthPointResponse } from "@/lib/api/types";

const MONTH_NAMES = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/** Turn '2026-03' into "Mar '26". */
function monthLabel(iso: string): string {
  const [year, month] = iso.split("-");
  const name = MONTH_NAMES[Number(month) - 1] ?? month;
  return `${name} '${year.slice(2)}`;
}

/**
 * A dependency-free month-by-month trend as horizontal bars (BP14). One row per month
 * (`month — bar — count`), so it reads cleanly whether there's a single month or twelve —
 * a vertical bar chart looks empty with few points. The bar is decorative (`aria-hidden`);
 * the month + count text carries the data for screen readers (no separate sr-only table).
 */
export function TrendChart({
  months,
  metric,
  label,
}: {
  months: MonthPointResponse[];
  metric: "photos" | "events";
  label: string;
}) {
  if (months.length === 0) {
    return <p className="text-body-sm text-ink-muted">No activity yet.</p>;
  }
  const max = Math.max(1, ...months.map((m) => m[metric]));

  return (
    <figure className="flex flex-col gap-3">
      <figcaption className="text-body-sm font-medium text-ink-secondary">{label}</figcaption>
      <ul className="flex flex-col gap-2">
        {months.map((m) => {
          const v = m[metric];
          const pct = Math.round((100 * v) / max);
          return (
            <li key={m.month} className="flex items-center gap-3">
              <span className="w-14 shrink-0 text-body-sm tabular-nums text-ink-muted">
                {monthLabel(m.month)}
              </span>
              <div
                className="h-2.5 flex-1 overflow-hidden rounded-full bg-surface-2/70"
                aria-hidden="true"
              >
                <div
                  className="h-full rounded-full bg-accent transition-all"
                  style={{ width: `${Math.max(pct, v > 0 ? 4 : 0)}%` }}
                />
              </div>
              <span className="w-12 shrink-0 text-right text-body-sm tabular-nums text-ink-secondary">
                {v.toLocaleString()}
              </span>
            </li>
          );
        })}
      </ul>
    </figure>
  );
}
