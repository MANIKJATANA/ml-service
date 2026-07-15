"use client";

import { useState } from "react";

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

/** Masonry grid of lazily-loaded media tiles; owns the Lightbox (open index + prev/next).
 *  `items` is the ordered id+type list (decisions/0035, 0043). `variant` picks the tile
 *  treatment: "grid" (staff) or "masonry" (natural aspect, the student surface — BP3). */
export function PhotoGrid({
  items,
  showAppearances = true,
  canManageAppearances = false,
  variant = "grid",
  onNotMe,
}: {
  items: GalleryItem[];
  showAppearances?: boolean;
  /** Staff surface (BP5): make the lightbox appearances panel editable (confirm/reject/undo
   *  + add-a-missed-student) for any photo. Server-gated by `match:review`. */
  canManageAppearances?: boolean;
  variant?: "grid" | "masonry";
  /** Student surface (BP5): a "This isn't me" action per photo in the lightbox. */
  onNotMe?: (mediaId: string) => Promise<void>;
}) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  // Parallel arrays aligned by index — the Lightbox navigates by index over both.
  const mediaIds = items.map((it) => it.id);
  const mediaTypes = items.map((it) => it.mediaType);

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
        {items.map((item, i) => (
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
