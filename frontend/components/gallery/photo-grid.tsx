"use client";

import { useState } from "react";

import { Lightbox } from "@/components/gallery/lightbox";
import { PhotoTile } from "@/components/gallery/photo-tile";

/** Masonry grid of lazily-loaded photo tiles; owns the Lightbox (open index + prev/next).
 *  `mediaIds` is the ordered id list — callers normalise MediaResponse/GalleryMediaResponse
 *  to ids before passing them in (decisions/0035). */
export function PhotoGrid({
  mediaIds,
  showAppearances = true,
}: {
  mediaIds: string[];
  showAppearances?: boolean;
}) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  return (
    <>
      <div className="columns-2 gap-2 sm:columns-3 lg:columns-4 [&>*]:mb-2 [&>*]:break-inside-avoid">
        {mediaIds.map((mediaId, i) => (
          <PhotoTile key={mediaId} mediaId={mediaId} index={i} onOpen={setOpenIndex} />
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
