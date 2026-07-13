"use client";

import useSWR from "swr";

import { myNotifications } from "@/lib/api/endpoints";
import type { MyNotificationsResponse } from "@/lib/api/types";

/**
 * The student's authoritative "new photos" signal (BP4, decisions/0041) — an unseen tally
 * (the nav badge) + the announced events. Shared SWR key `"me/notifications"` so the
 * `/me` page and the nav badge make one request. `enabled=false` (key → null) turns it off
 * for non-students (who'd 403), like `useDashboard` does for the staff badges.
 */
export function useMyNotifications(enabled = true) {
  const { data, error, isLoading, mutate } = useSWR<MyNotificationsResponse>(
    enabled ? "me/notifications" : null,
    myNotifications,
  );
  return { notifications: data, error, isLoading, mutate };
}
