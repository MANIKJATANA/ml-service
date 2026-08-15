"use client";

import { useEffect } from "react";

/**
 * Warn before the browser unloads the page — a tab close, reload, or navigation to an
 * external URL — while `active` is true (BP19d). Use it to guard a long, interruptible
 * operation (e.g. an upload in progress) so the user doesn't lose it by accident.
 *
 * The browser shows its own generic "Leave site?" prompt; the message can't be customized
 * (modern browsers ignore `returnValue`'s text — setting it is just what triggers the
 * prompt). This does NOT fire on in-app (client-side router) navigation — guard those with
 * an explicit confirm on the control that navigates.
 */
export function useBeforeUnload(active: boolean): void {
  useEffect(() => {
    if (!active) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = ""; // required to trigger the prompt in some browsers
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [active]);
}
