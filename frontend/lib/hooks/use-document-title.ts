"use client";

import { useEffect } from "react";

/**
 * Set the browser tab title to "{title} · Photos" while this page is mounted (BP25, R3-S2-08).
 * A client-side hook because the app's pages are Client Components (they can't export server
 * `metadata`); it's an internal app, so there's no SEO cost. Restores the prior title on
 * unmount so a page without the hook doesn't inherit a stale one.
 */
export function useDocumentTitle(title: string): void {
  useEffect(() => {
    const previous = document.title;
    document.title = `${title} · Photos`;
    return () => {
      document.title = previous;
    };
  }, [title]);
}
