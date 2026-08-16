"use client";

import { useSyncExternalStore } from "react";

function subscribe(callback: () => void): () => void {
  window.addEventListener("online", callback);
  window.addEventListener("offline", callback);
  return () => {
    window.removeEventListener("online", callback);
    window.removeEventListener("offline", callback);
  };
}

/**
 * Track the browser's online/offline status (BP25, R3-S4 L16) via `useSyncExternalStore` — the
 * React-sanctioned way to subscribe to an external store, so there's no setState-in-effect.
 * The server snapshot is `true` (assume online) so SSR + hydration match.
 */
export function useOnlineStatus(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => navigator.onLine,
    () => true,
  );
}
