"use client";

import useSWR from "swr";

import { myNotifications } from "@/lib/api/endpoints";
import type { MyNotificationsResponse } from "@/lib/api/types";

/**
 * The student's authoritative "new photos" signal (BP4, decisions/0041) — an unseen tally
 * (the nav badge) + the announced events. Shared SWR key `"me/notifications"` so the
 * `/me` page and the nav badge make one request. `enabled=false` (key → null) turns it off
 * for non-students (who'd 403), like `useDashboard` does for the staff badges.
 *
 * BP20 (R3-S3-11): this flagship signal must stay fresh, so it opts INTO revalidation
 * (per-hook, not the global no-poll default) — a kept-open tab lights up on focus + every
 * ~minute, instead of freezing at the once-per-session fetch.
 */
export function useMyNotifications(enabled = true) {
  const { data, error, isLoading, mutate } = useSWR<MyNotificationsResponse>(
    enabled ? "me/notifications" : null,
    myNotifications,
    { revalidateOnFocus: true, refreshInterval: 60_000 },
  );
  return { notifications: data, error, isLoading, mutate };
}
