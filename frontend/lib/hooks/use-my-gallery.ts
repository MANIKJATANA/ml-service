"use client";

import useSWR from "swr";

import { myEvents, myMedia } from "@/lib/api/endpoints";
import type { EventForStudentResponse, GalleryMediaResponse } from "@/lib/api/types";

/** The events the logged-in student appears in (self-scoped — decisions/0036). */
export function useMyEvents() {
  const { data, error, isLoading, mutate } = useSWR<EventForStudentResponse[]>(
    "me/events",
    myEvents,
  );
  return { events: data, error, isLoading, mutate };
}

/** The student's own photos — all of them (eventId null) or filtered to one event. */
export function useMyMedia(eventId: string | null) {
  const { data, error, isLoading, mutate } = useSWR<GalleryMediaResponse[]>(
    eventId ? `me/media?event_id=${eventId}` : "me/media",
    () => myMedia(eventId ?? undefined),
  );
  return { media: data, error, isLoading, mutate };
}
