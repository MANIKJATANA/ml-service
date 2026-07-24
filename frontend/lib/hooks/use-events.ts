"use client";

import useSWR from "swr";

import { getEvent, getEvents } from "@/lib/api/endpoints";
import type { EventListItem, EventResponse } from "@/lib/api/types";
import { type ListQuery, useInfiniteList } from "@/lib/hooks/use-infinite-list";

/** One server page at a time of the events list (BP9): search/sort/filter hit SQL. */
export function useEvents(query: ListQuery) {
  return useInfiniteList<EventListItem>("events", query, getEvents);
}

export function useEvent(eventId: string) {
  const { data, error, isLoading, mutate } = useSWR<EventResponse>(
    eventId ? `events/${eventId}` : null,
    () => getEvent(eventId),
  );
  return { event: data, error, isLoading, mutate };
}
