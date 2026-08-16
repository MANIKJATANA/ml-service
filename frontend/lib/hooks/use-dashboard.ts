"use client";

import useSWR from "swr";

import { getDashboard } from "@/lib/api/endpoints";
import type { DashboardResponse } from "@/lib/api/types";

/**
 * The school command-center rollup (BP1, decisions/0038). Shared SWR key `"dashboard"`
 * so the dashboard page and the nav's information-scent badges make ONE request.
 *
 * `enabled=false` (key → null) turns the fetch off for callers who can't view it
 * (platform_admin/student have no `dashboard:view` and would 403) — used by the shell.
 *
 * BP20 (R3-S3-11): opts into revalidation (per-hook) so the nav's attention badges + the
 * dashboard reflect colleagues' changes on focus + every ~minute, not once per session.
 */
export function useDashboard(enabled = true) {
  const { data, error, isLoading, mutate } = useSWR<DashboardResponse>(
    enabled ? "dashboard" : null,
    getDashboard,
    { revalidateOnFocus: true, refreshInterval: 60_000 },
  );
  return { dashboard: data, error, isLoading, mutate };
}
