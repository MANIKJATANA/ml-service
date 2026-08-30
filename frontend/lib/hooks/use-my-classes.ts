"use client";

import useSWR from "swr";

import { getMyClasses } from "@/lib/api/endpoints";
import type { ClassResponse } from "@/lib/api/types";

/**
 * The caller-teacher's own assigned classes (BP11c, decisions/0060) — the class ids their
 * students/events lists "focus" on. `enabled` gates the fetch off for non-teachers (an admin
 * isn't assigned to classes). Keyed on "my-classes" so a delegation change can refresh it.
 *
 * BP29 (R4-T06): opts into revalidation (per-hook, like use-dashboard) so an admin's
 * class assignment reaches the teacher on focus + every ~minute, not once per session. Stays
 * `enabled`-gated so a non-teacher never polls.
 */
export function useMyClasses(enabled: boolean) {
  const { data, error, isLoading, mutate } = useSWR<{ items: ClassResponse[] }>(
    enabled ? "my-classes" : null,
    getMyClasses,
    { revalidateOnFocus: true, refreshInterval: 60_000 },
  );
  return { classes: data?.items ?? [], error, isLoading, mutate };
}
