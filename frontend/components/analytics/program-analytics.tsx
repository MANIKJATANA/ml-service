"use client";

import { RateCard } from "@/components/analytics/rate-card";
import { TrendChart } from "@/components/analytics/trend-chart";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { SchoolAnalyticsResponse } from "@/lib/api/types";
import { useSchoolAnalytics } from "@/lib/hooks/use-school-analytics";

/**
 * The program-analytics section (BP14, decisions/0062), embedded in the school dashboard —
 * delivery/sign-in/engagement rates + a monthly trend + per-term rollups. Its own fetch
 * (`dashboard:view`, tenant from the token); a load/error here never blocks the rest of the
 * dashboard (a compact skeleton, a muted note on failure). Rendered only once the school has
 * data (the caller gates it), so the rate cards never show a wall of "—" on day one.
 */
export function ProgramAnalytics() {
  const { analytics, error, isLoading } = useSchoolAnalytics();

  if (isLoading && !analytics) {
    return (
      <section className="flex flex-col gap-3">
        <h2 className="text-headline text-ink">Program analytics</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Card key={i} className="flex flex-col gap-3 p-5">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-8 w-16" />
              <Skeleton className="h-1.5 w-full" />
              <Skeleton className="h-3 w-28" />
            </Card>
          ))}
        </div>
      </section>
    );
  }

  if (error || !analytics) {
    return (
      <section className="flex flex-col gap-3">
        <h2 className="text-headline text-ink">Program analytics</h2>
        <p className="text-body-sm text-ink-muted" role="alert">
          Couldn&apos;t load analytics right now.
        </p>
      </section>
    );
  }

  return <AnalyticsSection a={analytics} />;
}

function AnalyticsSection({ a }: { a: SchoolAnalyticsResponse }) {
  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-headline text-ink">Program analytics</h2>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <RateCard
          label="Announce rate"
          numerator={a.events_distributed}
          denominator={a.events_total}
          hint="events announced"
          tone="accent"
        />
        <RateCard
          label="Sign-in rate"
          numerator={a.students_signed_in}
          denominator={a.students_total}
          hint="students have signed in"
          tone="success"
        />
        <RateCard
          label="Engagement"
          numerator={a.students_engaged}
          denominator={a.students_total}
          hint="students opened their photos"
          tone="accent"
        />
      </div>

      {a.months.length > 0 ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="p-5">
            <TrendChart months={a.months} metric="photos" label="Photos uploaded / month" />
          </Card>
          <Card className="p-5">
            <TrendChart months={a.months} metric="events" label="Events / month" />
          </Card>
        </div>
      ) : null}

      {a.terms.length > 0 ? (
        <Card className="overflow-hidden">
          <table className="w-full text-body">
            <thead>
              <tr className="border-b border-hairline text-left text-body-sm text-ink-muted">
                <th scope="col" className="px-4 py-3 font-medium">Term</th>
                <th scope="col" className="px-4 py-3 text-right font-medium">Events</th>
                <th scope="col" className="px-4 py-3 text-right font-medium">Photos</th>
                <th scope="col" className="px-4 py-3 text-right font-medium">Announced</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline">
              {a.terms.map((t) => (
                <tr key={t.term}>
                  <td className="px-4 py-3 text-ink">{t.term}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-ink-secondary">{t.events}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-ink-secondary">
                    {t.photos.toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-ink-secondary">
                    {t.distributed} of {t.events}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      ) : null}
    </section>
  );
}
