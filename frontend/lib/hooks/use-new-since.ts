"use client";

import { useEffect, useRef, useState } from "react";

const key = (userId: string) => `seen-photos:${userId}`;

interface NewSince {
  newCount: number;
  firstVisit: boolean;
}

/**
 * Client-only "new since your last visit" tracking for the student gallery (BP3) — no
 * backend change. Persists (per user) the set of media ids the student has seen in
 * localStorage; on the first load of a session it computes how many of the current photos
 * weren't in that set, then folds the current ids in so they "count" next time.
 *
 * `firstVisit` is true when there's no stored set yet — the caller shows a welcome instead
 * of a misleading "everything is new". The read runs once (a ref guard), deferred to after
 * paint via rAF: the initial (server + hydration) render shows no banner — avoiding a
 * hydration mismatch — and the `setState` lands in an async callback, not synchronously in
 * the effect body.
 *
 * `mediaIds` MUST be the student's FULL (all-events) set — pass the unfiltered roster, never
 * a filtered subset, or the persisted seen-set would drop the omitted ids and resurface them
 * as "new" forever. The commit waits for a settled, non-empty set (a transient `[]` from an
 * in-flight/deduped SWR read must not lock in an empty seen-set).
 */
export function useNewSince(
  userId: string | undefined,
  mediaIds: string[] | undefined,
): NewSince {
  const [state, setState] = useState<NewSince>({ newCount: 0, firstVisit: false });
  const done = useRef(false);

  useEffect(() => {
    // Wait for a settled, non-empty roster: a student with events always has ≥1 photo, so
    // an empty array here means "not loaded yet", not "genuinely none".
    if (!userId || !mediaIds || mediaIds.length === 0 || done.current) return;
    done.current = true;

    const raf = requestAnimationFrame(() => {
      let stored: string | null = null;
      try {
        stored = localStorage.getItem(key(userId));
      } catch {
        return; // storage blocked (private mode) — silently skip the feature
      }

      const isFirst = stored === null;
      let seen: string[] = [];
      if (!isFirst) {
        try {
          seen = JSON.parse(stored ?? "[]");
        } catch {
          seen = [];
        }
      }
      const seenSet = new Set(seen);
      setState({
        newCount: isFirst ? 0 : mediaIds.filter((id) => !seenSet.has(id)).length,
        firstVisit: isFirst,
      });

      try {
        localStorage.setItem(key(userId), JSON.stringify([...new Set([...seen, ...mediaIds])]));
      } catch {
        // best-effort; the count is already shown
      }
    });
    return () => cancelAnimationFrame(raf);
  }, [userId, mediaIds]);

  return state;
}
