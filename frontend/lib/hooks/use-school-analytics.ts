"use client";

import useSWR from "swr";

import { getSchoolAnalytics } from "@/lib/api/endpoints";
import type { SchoolAnalyticsResponse } from "@/lib/api/types";

/**
 * The school program view (BP14, decisions/0062) — delivery/sign-in/engagement rates,
 * per-term rollups, and a monthly trend. Gated on `dashboard:view` (school_admin +
 * teacher); the analytics page is only in their nav.
 */
export function useSchoolAnalytics() {
  const { data, error, isLoading, mutate } = useSWR<SchoolAnalyticsResponse>(
    "analytics/school",
    getSchoolAnalytics,
  );
  return { analytics: data, error, isLoading, mutate };
}
