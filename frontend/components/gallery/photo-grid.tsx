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
  canManageAppearances = false,
  variant = "grid",
  onNotMe,
}: {
  mediaIds: string[];
  showAppearances?: boolean;
  /** Staff surface (BP5): make the lightbox appearances panel editable (confirm/reject/undo
   *  + add-a-missed-student) for any photo. Server-gated by `match:review`. */
  canManageAppearances?: boolean;
  variant?: "grid" | "masonry";
  /** Student surface (BP5): a "This isn't me" action per photo in the lightbox. */
  onNotMe?: (mediaId: string) => Promise<void>;
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
          canManageAppearances={canManageAppearances}
          onNotMe={onNotMe}
        />
      ) : null}
    </>
  );
}
