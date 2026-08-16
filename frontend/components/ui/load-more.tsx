"use client";

import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";

/**
 * The infinite-list footer (BP9, decisions/0055): an IntersectionObserver sentinel that
 * auto-loads the next page as it scrolls into view, plus an always-rendered "Load more"
 * button (the accessibility / reduced-motion fallback — never scroll-only) and a live
 * "Showing N of M". Renders nothing for an empty list.
 */
export function LoadMore({
  shown,
  total,
  reachedEnd,
  loading,
  onLoadMore,
}: {
  shown: number;
  total: number;
  reachedEnd: boolean;
  loading: boolean;
  onLoadMore: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || reachedEnd) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && !loading) onLoadMore();
      },
      { rootMargin: "400px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [reachedEnd, loading, onLoadMore]);

  if (total === 0) return null;

  return (
    <div ref={ref} className="flex flex-col items-center gap-2 py-4">
      {!reachedEnd ? (
        <Button variant="secondary" onClick={onLoadMore} loading={loading}>
          Load more
        </Button>
      ) : null}
      <span role="status" className="tabular-nums text-body-sm text-ink-secondary">
        Showing {shown} of {total}
      </span>
    </div>
  );
}
