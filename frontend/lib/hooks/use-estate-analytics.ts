"use client";

import useSWR from "swr";

import { getEstateAnalytics } from "@/lib/api/endpoints";
import type { EstateAnalyticsResponse } from "@/lib/api/types";

/**
 * The platform estate adoption view (BP14, decisions/0062) — per-school funnel + stalled/idle
 * flags + estate totals. Gated on `school:manage` (platform admin); the page lives in the
 * platform nav only.
 */
export function useEstateAnalytics() {
  const { data, error, isLoading, mutate } = useSWR<EstateAnalyticsResponse>(
    "analytics/estate",
    getEstateAnalytics,
  );
  return { estate: data, error, isLoading, mutate };
}
