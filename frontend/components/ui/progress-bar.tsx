import { cn } from "@/lib/utils";

/** A determinate progress bar (0–100). */
export function ProgressBar({
  value,
  label = "Progress",
  className,
}: {
  value: number;
  label?: string;
  className?: string;
}) {
  const pct = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuetext={`${pct}%`}
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-surface-2", className)}
    >
      <div
        className="h-full rounded-full bg-accent-hover transition-[width] duration-150"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
