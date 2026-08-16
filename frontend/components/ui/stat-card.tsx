import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface StatCardProps {
  /** What the number counts, in the reader's words ("Students", "Photos"). */
  label: string;
  value: number | string;
  /** A small secondary line — e.g. a breakdown ("18 enrolled · 2 failed"). */
  hint?: ReactNode;
  /** When set, the whole card is a link to the matching list, with a hover affordance. */
  href?: string;
}

/**
 * One headline metric for the admin dashboard (BP1): a big tabular number over a muted
 * label, optionally linking to the list it summarizes. Tabular numerals keep columns of
 * cards aligned — the Stripe-grade "numbers are data" bar for the staff surface.
 */
export function StatCard({ label, value, hint, href }: StatCardProps) {
  const body = (
    <>
      <span className="text-body-sm text-ink-secondary">{label}</span>
      <span className="text-display-lg tabular-nums text-ink">{value}</span>
      {hint ? <span className="text-body-sm text-ink-secondary">{hint}</span> : null}
    </>
  );
  const base =
    "flex flex-col gap-1 rounded-card border border-hairline bg-canvas p-5 shadow-sm";
  if (href) {
    return (
      <Link
        href={href}
        className={cn(
          base,
          "transition-colors hover:border-hairline-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-surface",
        )}
      >
        {body}
      </Link>
    );
  }
  return <div className={base}>{body}</div>;
}
