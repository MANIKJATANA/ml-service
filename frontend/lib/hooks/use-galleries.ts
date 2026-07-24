"use client";

import useSWR from "swr";

import {
  eventReview,
  eventStudentMedia,
  eventStudents,
  getEventMedia,
  getMedia,
  mediaAppearances,
  studentEvents,
  studentMedia,
} from "@/lib/api/endpoints";
import type {
  EventForStudentResponse,
  GalleryMediaResponse,
  MediaAppearanceResponse,
  MediaResponse,
  MediaReviewResponse,
  StudentInEventResponse,
} from "@/lib/api/types";
import { useInfiniteList } from "@/lib/hooks/use-infinite-list";

/** One server page at a time of an event's photos (browse-all gallery, BP9). */
export function useEventMedia(eventId: string) {
  return useInfiniteList<MediaResponse>(
    eventId ? `events/${eventId}/media` : null,
    {},
    (params) => getEventMedia(eventId, params),
  );
}

/** Students who appear in an event (+ per-student photo counts). */
export function useEventStudents(eventId: string) {
  const { data, error, isLoading, mutate } = useSWR<StudentInEventResponse[]>(
    eventId ? `events/${eventId}/students` : null,
    () => eventStudents(eventId),
  );
  return { students: data, error, isLoading, mutate };
}

/** One student's photos within one event (null studentId → not fetched). */
export function useEventStudentMedia(eventId: string, studentId: string | null) {
  const { data, error, isLoading } = useSWR<GalleryMediaResponse[]>(
    eventId && studentId ? `events/${eventId}/students/${studentId}/media` : null,
    () => eventStudentMedia(eventId, studentId as string),
  );
  return { media: data, error, isLoading };
}

/** Events a student appears in (+ per-event photo counts). */
export function useStudentEvents(studentId: string) {
  const { data, error, isLoading } = useSWR<EventForStudentResponse[]>(
    studentId ? `students/${studentId}/events` : null,
    () => studentEvents(studentId),
  );
  return { events: data, error, isLoading };
}

/** One student's photos in a given event (null eventId → not fetched). */
export function useStudentMedia(studentId: string, eventId: string | null) {
  const { data, error, isLoading } = useSWR<GalleryMediaResponse[]>(
    studentId && eventId ? `students/${studentId}/media?event_id=${eventId}` : null,
    () => studentMedia(studentId, eventId as string),
  );
  return { media: data, error, isLoading };
}

/** One media's own row (used for the photo page's event context). */
export function useMedia(mediaId: string) {
  const { data, error, isLoading } = useSWR<MediaResponse>(
    mediaId ? `media/${mediaId}` : null,
    () => getMedia(mediaId),
  );
  return { media: data, error, isLoading };
}

/** Who appears in one photo (names + confidence + needs_review + verdict). */
export function useMediaAppearances(mediaId: string | null) {
  const { data, error, isLoading, mutate } = useSWR<MediaAppearanceResponse[]>(
    mediaId ? `media/${mediaId}/appearances` : null,
    () => mediaAppearances(mediaId as string),
  );
  return { appearances: data, error, isLoading, mutate };
}

/** The event's unresolved ambiguous matches grouped by photo — the review lane (BP5). */
export function useEventReview(eventId: string) {
  const { data, error, isLoading, mutate } = useSWR<MediaReviewResponse[]>(
    eventId ? `events/${eventId}/review` : null,
    () => eventReview(eventId),
  );
  return { reviews: data, error, isLoading, mutate };
}
