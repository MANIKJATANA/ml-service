"use client";

import useSWR from "swr";

import { getEventStatus } from "@/lib/api/endpoints";
import type { EventStatusResponse } from "@/lib/api/types";

// While the event is on the queue or being worked, the ML worker can still advance it,
// so poll; once completed / not_started, stop (SWR treats a 0 interval as "no polling").
const IN_FLIGHT = new Set<string>(["queued", "processing"]);

export function useEventStatus(eventId: string) {
  const { data, error, isLoading, mutate } = useSWR<EventStatusResponse>(
    eventId ? `events/${eventId}/status` : null,
    () => getEventStatus(eventId),
    {
      refreshInterval: (latest) =>
        latest && IN_FLIGHT.has(latest.processing_status) ? 2500 : 0,
    },
  );
  return { status: data, error, isLoading, mutate };
}
