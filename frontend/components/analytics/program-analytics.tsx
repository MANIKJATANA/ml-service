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
        <p className="text-body-sm text-ink-secondary" role="alert">
          Couldn&apos;t load analytics right now.
        </p>
      </section>
    );
  }

  return <AnalyticsSection a={analytics} />;
}

function AnalyticsSection({ a }: { a: SchoolAnalyticsResponse }) {
  // BP23: matching quality — sum the monthly verdicts. `added` (report-a-miss = a recall
  // signal) is shown on its own, never folded into the confirm/reject precision denominator.
  const confirmed = a.quality.reduce((s, q) => s + q.confirmed, 0);
  const rejected = a.quality.reduce((s, q) => s + q.rejected, 0);
  const added = a.quality.reduce((s, q) => s + q.added, 0);
  const adjudicated = confirmed + rejected;

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
          label="Open rate"
          numerator={a.events_opened}
          denominator={a.events_distributed}
          hint="announced events opened by someone"
          tone="success"
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
        <RateCard
          label="Saved a photo"
          numerator={a.students_saved}
          denominator={a.students_total}
          hint="students saved a photo"
          tone="accent"
        />
      </div>

      {a.months.length > 0 ? (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="p-5">
            <TrendChart months={a.months} metric="photos" label="Photos uploaded / month" />
          </Card>
          <Card className="p-5">
            <TrendChart months={a.months} metric="events" label="Events / month" />
          </Card>
          <Card className="p-5">
            <TrendChart
              months={a.months}
              metric="first_opens"
              label="Students opening photos / month"
            />
          </Card>
        </div>
      ) : null}

      {adjudicated > 0 || added > 0 ? (
        <div className="flex flex-col gap-3">
          <h3 className="text-body font-semibold text-ink">Matching quality</h3>
          <p className="text-body-sm text-ink-secondary">
            {adjudicated > 0
              ? `Of the ${adjudicated.toLocaleString()} matches your staff reviewed, how many they kept — a rising "wrong person" rate is worth a look. `
              : "How your staff have corrected the matching so far. "}
            <a href="/how-matching-works" className="rounded-sm text-accent underline hover:text-accent-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
              How matching works
            </a>
          </p>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {adjudicated > 0 ? (
              <>
                <RateCard
                  label="Confirm rate"
                  numerator={confirmed}
                  denominator={adjudicated}
                  hint="reviewed matches kept"
                  tone="success"
                />
                <RateCard
                  label="Wrong-person rate"
                  numerator={rejected}
                  denominator={adjudicated}
                  hint="reviewed matches rejected"
                  tone="warning"
                />
              </>
            ) : null}
            <Card className="flex flex-col justify-center gap-1 p-5">
              <span className="text-body-sm text-ink-secondary">Photos staff added</span>
              <span className="text-display-lg tabular-nums text-ink">
                {added.toLocaleString()}
              </span>
              <span className="text-body-sm text-ink-secondary">
                students the match missed (report-a-miss)
              </span>
            </Card>
          </div>
        </div>
      ) : null}

      {a.terms.length > 0 ? (
        <Card className="overflow-hidden">
          <table className="w-full text-body">
            <thead>
              <tr className="border-b border-hairline text-left text-body-sm text-ink-secondary">
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
