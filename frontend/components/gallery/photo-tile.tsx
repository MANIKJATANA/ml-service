"use client";

import { Download, Play } from "lucide-react";

import { SignedImage } from "@/components/gallery/signed-image";
import type { MediaType } from "@/lib/api/types";
import { useDownloadToDisk } from "@/lib/hooks/use-download-to-disk";
import { useInView } from "@/lib/hooks/use-in-view";
import { useMediaDownload } from "@/lib/hooks/use-media-download";

interface PhotoTileProps {
  mediaId: string;
  index: number;
  onOpen: (index: number) => void;
  /** The media's type — a video renders a first-frame poster + a play badge (BP6). */
  mediaType?: MediaType;
  /** BP17: whether a display thumbnail exists — the tile requests the small ?size=thumb only
   *  when true, else the full-res object (a pre-BP17 image still renders). Video ignores it
   *  (it always uses the full object as its poster). */
  hasThumbnail?: boolean;
  /** "grid" = uniform square crop (staff galleries); "masonry" = natural aspect ratio,
   *  borderless, with a hover-to-download affordance (the student surface, BP3). */
  variant?: "grid" | "masonry";
}

/** A play badge overlaid on a video tile so it reads as playable (BP6). */
function PlayBadge() {
  return (
    <span
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 flex items-center justify-center"
    >
      <span className="flex size-11 items-center justify-center rounded-full bg-ink/55 text-canvas shadow-md">
        <Play className="size-5 translate-x-px fill-current" />
      </span>
    </span>
  );
}

/** One photo in a grid. Defers its signed-URL fetch until near the viewport (useInView). */
export function PhotoTile({
  mediaId,
  index,
  onOpen,
  mediaType = "image",
  hasThumbnail = false,
  variant = "grid",
}: PhotoTileProps) {
  const props = { mediaId, index, onOpen, mediaType, hasThumbnail };
  return variant === "masonry" ? <MasonryTile {...props} /> : <GridTile {...props} />;
}

/** Staff galleries: uniform square crop, bordered — dense and scannable (unchanged). */
function GridTile({
  mediaId,
  index,
  onOpen,
  mediaType,
  hasThumbnail,
}: Omit<PhotoTileProps, "variant">) {
  const { ref, inView } = useInView<HTMLButtonElement>();
  const isVideo = mediaType === "video";
  return (
    <button
      ref={ref}
      type="button"
      onClick={() => onOpen(index)}
      aria-label={`Open ${isVideo ? "video" : "photo"} ${index + 1}`}
      className="relative block w-full overflow-hidden rounded-card border border-hairline bg-surface-2 transition-colors hover:border-hairline-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <SignedImage
        mediaId={mediaId}
        kind={mediaType}
        enabled={inView}
        size={hasThumbnail ? "thumb" : "full"}
        alt=""
        loading="square"
        className="aspect-square w-full"
        imgClassName="block w-full align-top"
        fallbackText="Unavailable"
      />
      {isVideo ? <PlayBadge /> : null}
    </button>
  );
}

/** Student surface: the photo is the hero — natural aspect ratio in a masonry column, a
 *  gentle zoom on hover, and a hover-revealed download so a photo can be saved in one tap
 *  without opening the viewer (BP3). */
function MasonryTile({
  mediaId,
  index,
  onOpen,
  mediaType,
  hasThumbnail,
}: Omit<PhotoTileProps, "variant">) {
  const { ref, inView } = useInView<HTMLDivElement>();
  const { download } = useMediaDownload(mediaId, inView);
  const { downloading, onDownload } = useDownloadToDisk(mediaId, download);
  const isVideo = mediaType === "video";

  return (
    <div ref={ref} className="group relative overflow-hidden rounded-2xl bg-surface-2">
      <button
        type="button"
        onClick={() => onOpen(index)}
        aria-label={`Open ${isVideo ? "video" : "photo"} ${index + 1}`}
        className="relative block w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <SignedImage
          mediaId={mediaId}
          kind={mediaType}
          enabled={inView}
          size={hasThumbnail ? "thumb" : "full"}
          alt=""
          loading="block"
          className="aspect-[3/4] rounded-2xl"
          imgClassName="block w-full align-top transition-transform duration-300 group-hover:scale-[1.03]"
          fallbackText="Unavailable"
        />
        {isVideo ? <PlayBadge /> : null}
      </button>
      {/* Gradient scrim + download, revealed on hover / keyboard focus. */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-end bg-gradient-to-t from-ink/40 to-transparent p-2 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        <button
          type="button"
          onClick={onDownload}
          disabled={!download || downloading}
          aria-label={`Download photo ${index + 1}`}
          className="pointer-events-auto rounded-full bg-canvas/90 p-2 text-ink shadow-md transition-colors hover:bg-canvas focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
        >
          <Download className="size-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
