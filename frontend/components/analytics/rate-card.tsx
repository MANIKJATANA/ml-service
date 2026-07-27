import { cn } from "@/lib/utils";

interface RateCardProps {
  /** What the rate measures ("Delivery rate", "Sign-in rate"). */
  label: string;
  /** The numerator + denominator; the percentage is derived. */
  numerator: number;
  denominator: number;
  /** A short plain-language description of the fraction ("events announced"). */
  hint: string;
  tone?: "accent" | "success" | "warning";
}

const BAR_TONE: Record<NonNullable<RateCardProps["tone"]>, string> = {
  accent: "bg-accent",
  success: "bg-success-strong",
  warning: "bg-warning-strong",
};

/**
 * One program rate for the analytics page (BP14): a big percentage over its raw fraction,
 * with a slim progress bar. The percentage is rounded here (one place); a zero denominator
 * reads as "—" rather than a misleading 0%.
 */
export function RateCard({
  label,
  numerator,
  denominator,
  hint,
  tone = "accent",
}: RateCardProps) {
  const hasData = denominator > 0;
  const pct = hasData ? Math.round((100 * numerator) / denominator) : 0;
  return (
    <div className="flex flex-col gap-2 rounded-card border border-hairline bg-canvas p-5 shadow-sm">
      <span className="text-body-sm text-ink-muted">{label}</span>
      <span className="text-display-lg tabular-nums text-ink">
        {hasData ? `${pct}%` : "—"}
      </span>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label}: ${pct}%`}
      >
        <div
          className={cn("h-full rounded-full transition-all", BAR_TONE[tone])}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-body-sm text-ink-secondary tabular-nums">
        {numerator.toLocaleString()} of {denominator.toLocaleString()} {hint}
      </span>
    </div>
  );
}
