"use client";

import { useEffect, useRef, useState } from "react";

import { Lightbox } from "@/components/gallery/lightbox";
import { PhotoTile } from "@/components/gallery/photo-tile";
import type { MediaType } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/** One media in a grid: its id + type (image vs video). Callers normalise
 *  MediaResponse/GalleryMediaResponse into these before passing them in (BP6). */
export interface GalleryItem {
  id: string;
  mediaType: MediaType;
}

// How many tiles to mount initially + grow per scroll step (BP9) — bounds the DOM/mount
// cost so a 900-photo gallery never mounts 900 IntersectionObserver tiles at once.
const INITIAL_WINDOW = 48;
const WINDOW_STEP = 48;

/** Masonry grid of lazily-loaded media tiles; owns the Lightbox (open index + prev/next).
 *  `items` is the ordered id+type list (decisions/0035, 0043). `variant` picks the tile
 *  treatment: "grid" (staff) or "masonry" (natural aspect, the student surface — BP3).
 *
 *  Scale (BP9, decisions/0055): the grid **windows** — it mounts only the first N tiles and
 *  grows N as a sentinel scrolls into view. When the window reaches the end of the loaded
 *  items and `onLoadMore`/`hasMore` are given (a server-paginated source), it fetches the
 *  next page. The Lightbox still navigates the whole loaded set. */
export function PhotoGrid({
  items,
  showAppearances = true,
  canManageAppearances = false,
  variant = "grid",
  onNotMe,
  onLoadMore,
  hasMore = false,
  loadingMore = false,
}: {
  items: GalleryItem[];
  showAppearances?: boolean;
  /** Staff surface (BP5): make the lightbox appearances panel editable (confirm/reject/undo
   *  + add-a-missed-student) for any photo. Server-gated by `match:review`. */
  canManageAppearances?: boolean;
  variant?: "grid" | "masonry";
  /** Student surface (BP5): a "This isn't me" action per photo in the lightbox. */
  onNotMe?: (mediaId: string) => Promise<void>;
  /** BP9: for a server-paginated source, fetch the next page when the window reaches the
   *  end of the loaded items. Omit for a fully-loaded source (windowing still applies). */
  onLoadMore?: () => void;
  hasMore?: boolean;
  loadingMore?: boolean;
}) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const [visibleCount, setVisibleCount] = useState(INITIAL_WINDOW);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // Reset the window when the gallery source changes (a new first item = a new gallery /
  // filter). Growth (server pages appended) keeps the same first item, so it doesn't reset.
  // The React-sanctioned "adjust state during render" pattern (no setState-in-effect).
  const firstId = items[0]?.id;
  const [prevFirstId, setPrevFirstId] = useState(firstId);
  if (firstId !== prevFirstId) {
    setPrevFirstId(firstId);
    setVisibleCount(INITIAL_WINDOW);
  }

  // Parallel arrays aligned by index over the FULL loaded set — the Lightbox navigates both.
  const mediaIds = items.map((it) => it.id);
  const mediaTypes = items.map((it) => it.mediaType);
  const shown = items.slice(0, visibleCount);
  const canGrow = visibleCount < items.length;
  const canFetch = hasMore && !loadingMore;

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || (!canGrow && !canFetch)) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries[0]?.isIntersecting) return;
        if (canGrow) setVisibleCount((v) => v + WINDOW_STEP);
        else if (canFetch) onLoadMore?.();
      },
      { rootMargin: "600px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [canGrow, canFetch, onLoadMore]);

  return (
    <>
      <div
        className={cn(
          "columns-2 sm:columns-3 [&>*]:break-inside-avoid",
          variant === "masonry"
            ? "gap-3 lg:columns-4 [&>*]:mb-3"
            : "gap-2 lg:columns-4 [&>*]:mb-2",
        )}
      >
        {shown.map((item, i) => (
          <PhotoTile
            key={item.id}
            mediaId={item.id}
            mediaType={item.mediaType}
            index={i}
            onOpen={setOpenIndex}
            variant={variant}
          />
        ))}
      </div>
      {canGrow || hasMore ? (
        <div ref={sentinelRef} aria-hidden="true" className="h-1 w-full" />
      ) : null}
      {openIndex !== null ? (
        <Lightbox
          mediaIds={mediaIds}
          mediaTypes={mediaTypes}
          index={openIndex}
          onIndexChange={setOpenIndex}
          onClose={() => setOpenIndex(null)}
          showAppearances={showAppearances}
          canManageAppearances={canManageAppearances}
          onNotMe={onNotMe}
        />
      ) : null}
    </>
  );
}
