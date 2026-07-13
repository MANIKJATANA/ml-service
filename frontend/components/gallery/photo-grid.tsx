"use client";

import { useState } from "react";

import { Lightbox } from "@/components/gallery/lightbox";
import { PhotoTile } from "@/components/gallery/photo-tile";
import { cn } from "@/lib/utils";

/** Masonry grid of lazily-loaded photo tiles; owns the Lightbox (open index + prev/next).
 *  `mediaIds` is the ordered id list — callers normalise MediaResponse/GalleryMediaResponse
 *  to ids before passing them in (decisions/0035). `variant` picks the tile treatment:
 *  "grid" (uniform square, staff) or "masonry" (natural aspect, the student surface — BP3). */
export function PhotoGrid({
  mediaIds,
  showAppearances = true,
  variant = "grid",
}: {
  mediaIds: string[];
  showAppearances?: boolean;
  variant?: "grid" | "masonry";
}) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);

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
        {mediaIds.map((mediaId, i) => (
          <PhotoTile key={mediaId} mediaId={mediaId} index={i} onOpen={setOpenIndex} variant={variant} />
        ))}
      </div>
      {openIndex !== null ? (
        <Lightbox
          mediaIds={mediaIds}
          index={openIndex}
          onIndexChange={setOpenIndex}
          onClose={() => setOpenIndex(null)}
          showAppearances={showAppearances}
        />
      ) : null}
    </>
  );
}
