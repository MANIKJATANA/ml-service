"use client";

import { SignedImage } from "@/components/gallery/signed-image";
import { useInView } from "@/lib/hooks/use-in-view";

interface PhotoTileProps {
  mediaId: string;
  index: number;
  onOpen: (index: number) => void;
}

/** One masonry tile: defers its signed-URL fetch until near the viewport (via useInView),
 *  then renders the image full-bleed. Click opens the Lightbox (decisions/0035). */
export function PhotoTile({ mediaId, index, onOpen }: PhotoTileProps) {
  const { ref, inView } = useInView<HTMLButtonElement>();

  return (
    <button
      ref={ref}
      type="button"
      onClick={() => onOpen(index)}
      aria-label={`Open photo ${index + 1}`}
      className="mb-2 block w-full overflow-hidden rounded-card border border-hairline bg-surface-2 transition-colors hover:border-hairline-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <SignedImage
        mediaId={mediaId}
        enabled={inView}
        alt=""
        loading="square"
        className="aspect-square w-full"
        imgClassName="block w-full align-top"
        fallbackText="Unavailable"
      />
    </button>
  );
}
