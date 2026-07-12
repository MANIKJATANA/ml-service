"use client";

import useSWR from "swr";

import { getEvent, listEvents } from "@/lib/api/endpoints";
import type { EventResponse } from "@/lib/api/types";

export function useEvents() {
  const { data, error, isLoading, mutate } = useSWR<EventResponse[]>("events", listEvents);
  return { events: data, error, isLoading, mutate };
}

export function useEvent(eventId: string) {
  const { data, error, isLoading, mutate } = useSWR<EventResponse>(
    eventId ? `events/${eventId}` : null,
    () => getEvent(eventId),
  );
  return { event: data, error, isLoading, mutate };
}
