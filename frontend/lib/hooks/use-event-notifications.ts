"use client";

import useSWR from "swr";

import { eventNotifications } from "@/lib/api/endpoints";
import type { NotificationRosterResponse } from "@/lib/api/types";

/** The staff "notified / seen" roster for one event (BP4, decisions/0041). */
export function useEventNotifications(eventId: string) {
  const { data, error, isLoading, mutate } = useSWR<NotificationRosterResponse>(
    eventId ? `events/${eventId}/notifications` : null,
    () => eventNotifications(eventId),
  );
  return { roster: data, error, isLoading, mutate };
}
