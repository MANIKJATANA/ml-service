"use client";

import { Info, X } from "lucide-react";
import { useSyncExternalStore } from "react";

import { useMe } from "@/lib/hooks/use-me";
import { useMyClasses } from "@/lib/hooks/use-my-classes";

const DISMISS_KEY = "bp29-delegation-banner-dismissed";
const DISMISS_EVENT = "bp29-delegation-banner-dismiss";

function subscribe(callback: () => void): () => void {
  window.addEventListener(DISMISS_EVENT, callback);
  return () => window.removeEventListener(DISMISS_EVENT, callback);
}

/**
 * Whether the delegation banner has been dismissed, read via `useSyncExternalStore` — the
 * React-sanctioned way to subscribe to an external store (localStorage), so there's no
 * setState-in-effect and no hydration mismatch. The server snapshot is `false` (default =
 * shown), so SSR/prerender + the first client render agree. Dismissal writes the flag and
 * dispatches a same-tab event so this hook re-reads (localStorage's `storage` event only fires
 * cross-tab).
 */
function useBannerDismissed(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => localStorage.getItem(DISMISS_KEY) === "1",
    () => false,
  );
}

/**
 * Delegation-clarity banner (BP29, R4-T01): tells an un-delegated teacher WHY their lists show
 * every class — they have no classes assigned — and points them at their admin. Self-contained:
 * reads its own role + my-classes, so a page just drops it in.
 *
 * The `role === "teacher"` guard is load-bearing: an admin's `useMyClasses` is disabled and also
 * returns `[]`, so guarding on `length === 0` alone would wrongly show this to admins.
 */
export function DelegationBanner() {
  const { user } = useMe();
  const isTeacher = user?.role === "teacher";
  const { classes: myClasses, isLoading } = useMyClasses(isTeacher);
  const dismissed = useBannerDismissed();

  if (!isTeacher || isLoading || myClasses.length > 0 || dismissed) return null;

  function dismiss() {
    localStorage.setItem(DISMISS_KEY, "1");
    window.dispatchEvent(new Event(DISMISS_EVENT));
  }

  return (
    <div
      role="status"
      className="flex items-start gap-3 rounded-card border border-hairline bg-surface-2 px-4 py-3"
    >
      <Info className="mt-0.5 size-4 shrink-0 text-info-strong" aria-hidden="true" />
      <p className="min-w-0 flex-1 text-body-sm text-ink-secondary">
        You&apos;re seeing all classes. Ask your admin to assign you classes to focus your lists.
      </p>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss"
        className="-m-1 shrink-0 rounded p-1 text-ink-muted transition-colors hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <X className="size-4" aria-hidden="true" />
      </button>
    </div>
  );
}
