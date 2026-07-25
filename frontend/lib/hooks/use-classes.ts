"use client";

import useSWR from "swr";

import { getClasses } from "@/lib/api/endpoints";
import type { ClassListItem } from "@/lib/api/types";

/**
 * The school's classes (BP11a, decisions/0058) — bounded per school, so one unpaginated
 * fetch. Feeds the Classes page, the students-list class filter, and the student-detail class
 * selector. Keyed on "classes" so a create/rename/delete can `mutate("classes")` app-wide.
 */
export function useClasses() {
  const { data, error, isLoading, mutate } = useSWR<{ items: ClassListItem[] }>(
    "classes",
    getClasses,
  );
  return { classes: data?.items ?? [], error, isLoading, mutate };
}
