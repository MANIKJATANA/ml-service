"use client";

import useSWR from "swr";

import { getEvents } from "@/lib/api/endpoints";

export interface MonthFilters {
  category_id?: string;
  term?: string;
  status?: string;
  student_group_id?: string; // BP11c: the class filter
  mine?: boolean; // BP11c: a teacher's focus scope
}

/**
 * The events within a calendar grid's date window (BP11b) — one bounded fetch (a month is a few
 * dozen events at most), NOT the infinite list. Keyed on the window + filters; fetches the full
 * 6-week grid range so the leading/trailing spillover cells render their pills too.
 */
export function useMonthEvents(gridStart: string, gridEnd: string, f: MonthFilters) {
  const key = [
    "month-events",
    gridStart,
    gridEnd,
    f.category_id ?? "",
    f.term ?? "",
    f.status ?? "",
    f.student_group_id ?? "",
    f.mine ? "mine" : "",
  ];
  const { data, error, isLoading, mutate } = useSWR(key, () =>
    getEvents({
      limit: 200,
      offset: 0,
      date_from: gridStart,
      date_to: gridEnd,
      category_id: f.category_id || undefined,
      term: f.term || undefined,
      status: f.status && f.status !== "all" ? f.status : undefined,
      student_group_id: f.student_group_id || undefined,
      mine: f.mine,
    }),
  );
  return {
    events: data?.items ?? [],
    total: data?.total ?? 0,
    error,
    isLoading,
    mutate,
  };
}
