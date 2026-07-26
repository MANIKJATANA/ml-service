"use client";

import useSWR from "swr";

import { getEventCategories, getEventTerms } from "@/lib/api/endpoints";
import type { EventCategoryResponse } from "@/lib/api/types";

/**
 * The school's event categories (BP11b, decisions/0059) — bounded, one fetch. Keyed
 * "event-categories" so a create/delete can `mutate("event-categories")` app-wide (the events
 * filter, the create/edit picker, and the Manage-categories panel all read it).
 */
export function useEventCategories() {
  const { data, error, isLoading, mutate } = useSWR<EventCategoryResponse[]>(
    "event-categories",
    getEventCategories,
  );
  return { categories: data ?? [], error, isLoading, mutate };
}

/** The distinct terms the school has used (BP11b) — feeds the events term filter. Keyed
 *  "event-terms" so creating an event with a new term can `mutate("event-terms")`. */
export function useEventTerms() {
  const { data } = useSWR<{ terms: string[] }>("event-terms", getEventTerms);
  return data?.terms ?? [];
}
