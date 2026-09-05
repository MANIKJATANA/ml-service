"use client";

import { Check, Download, Play } from "lucide-react";

import { SignedImage } from "@/components/gallery/signed-image";
import type { MediaType } from "@/lib/api/types";
import { useDownloadToDisk } from "@/lib/hooks/use-download-to-disk";
import { useInView } from "@/lib/hooks/use-in-view";
import { useMediaDownload } from "@/lib/hooks/use-media-download";
import { cn } from "@/lib/utils";

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
  /** BP20: the photo's "story" (event + date) — its accessible name, a hover scrim label
   *  (masonry), and the saved filename. Omitted on surfaces that don't supply it. */
  caption?: string;
  /** Both variants are a uniform square crop; the variant only picks the chrome — "grid"
   *  (staff: bordered, selectable) vs "masonry" (student: rounded, hover zoom + hover-download,
   *  BP3). */
  variant?: "grid" | "masonry";
  /** BP13 multi-select (staff "grid" only): when on, a tile click toggles selection instead of
   *  opening the lightbox, and a checkmark overlay + ring show the selected state. */
  selectionMode?: boolean;
  selected?: boolean;
  onToggleSelect?: (mediaId: string) => void;
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
  caption,
  variant = "grid",
  selectionMode = false,
  selected = false,
  onToggleSelect,
}: PhotoTileProps) {
  const props = { mediaId, index, onOpen, mediaType, hasThumbnail, caption };
  // Multi-select is a staff-grid affordance only; the student masonry surface ignores it.
  return variant === "masonry" ? (
    <MasonryTile {...props} />
  ) : (
    <GridTile
      {...props}
      selectionMode={selectionMode}
      selected={selected}
      onToggleSelect={onToggleSelect}
    />
  );
}

/** Staff galleries: uniform square crop, bordered — dense and scannable. In BP13 selection
 *  mode a click toggles selection instead of opening the lightbox. */
function GridTile({
  mediaId,
  index,
  onOpen,
  mediaType,
  hasThumbnail,
  caption,
  selectionMode = false,
  selected = false,
  onToggleSelect,
}: Omit<PhotoTileProps, "variant">) {
  const { ref, inView } = useInView<HTMLButtonElement>();
  const isVideo = mediaType === "video";
  const kind = isVideo ? "video" : "photo";
  const name = caption ?? `${kind} ${index + 1}`;
  return (
    <button
      ref={ref}
      type="button"
      onClick={() => (selectionMode ? onToggleSelect?.(mediaId) : onOpen(index))}
      aria-label={
        selectionMode
          ? `${selected ? "Deselect" : "Select"} ${name}`
          : `Open ${name}`
      }
      aria-pressed={selectionMode ? selected : undefined}
      className={cn(
        "relative block w-full overflow-hidden rounded-card border bg-surface-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selected ? "border-accent-hover ring-2 ring-ring" : "border-hairline hover:border-hairline-strong",
      )}
    >
      <SignedImage
        mediaId={mediaId}
        kind={mediaType}
        enabled={inView}
        size={hasThumbnail ? "thumb" : "full"}
        alt=""
        loading="square"
        className="aspect-square w-full"
        // Fill the square and crop (object-cover) so every tile is the same size regardless of
        // the photo's real aspect; the Lightbox shows it uncropped.
        imgClassName="block aspect-square w-full object-cover align-top"
        fallbackText="Unavailable"
      />
      {isVideo ? <PlayBadge /> : null}
      {selectionMode ? (
        <span
          aria-hidden="true"
          className={cn(
            "absolute left-2 top-2 flex size-6 items-center justify-center rounded-full border shadow-sm transition-colors",
            selected
              ? "border-accent-hover bg-accent-hover text-canvas"
              : "border-hairline bg-canvas/85 text-transparent",
          )}
        >
          <Check className="size-4" />
        </span>
      ) : null}
    </button>
  );
}

/** Student surface: a uniform square crop, rounded, with a gentle zoom on hover and a
 *  hover-revealed download so a photo can be saved in one tap without opening the viewer (BP3). */
function MasonryTile({
  mediaId,
  index,
  onOpen,
  mediaType,
  hasThumbnail,
  caption,
}: Omit<PhotoTileProps, "variant">) {
  const { ref, inView } = useInView<HTMLDivElement>();
  const { download } = useMediaDownload(mediaId, inView);
  const { downloading, onDownload } = useDownloadToDisk(mediaId, download, caption);
  const isVideo = mediaType === "video";
  const name = caption ?? `${isVideo ? "video" : "photo"} ${index + 1}`;

  return (
    <div ref={ref} className="group relative overflow-hidden rounded-2xl bg-surface-2">
      <button
        type="button"
        onClick={() => onOpen(index)}
        aria-label={`Open ${name}`}
        className="relative block w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <SignedImage
          mediaId={mediaId}
          kind={mediaType}
          enabled={inView}
          size={hasThumbnail ? "thumb" : "full"}
          alt=""
          loading="square"
          className="aspect-square w-full rounded-2xl"
          // Uniform square, cropped to fill (object-cover) — same size as every other tile.
          imgClassName="block aspect-square w-full object-cover align-top transition-transform duration-300 group-hover:scale-[1.03]"
          fallbackText="Unavailable"
        />
        {isVideo ? <PlayBadge /> : null}
      </button>
      {/* Gradient scrim: the photo's story (BP20) + a download, revealed on hover / focus. */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between gap-2 bg-gradient-to-t from-ink/50 to-transparent p-2 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        {caption ? (
          <span
            aria-hidden="true"
            className="min-w-0 flex-1 truncate pb-1 pl-1 text-body-sm font-medium text-canvas drop-shadow"
          >
            {caption}
          </span>
        ) : (
          <span className="flex-1" />
        )}
        <button
          type="button"
          onClick={onDownload}
          disabled={!download || downloading}
          aria-label={`Download ${name}`}
          className="pointer-events-auto shrink-0 rounded-full bg-canvas/90 p-2 text-ink shadow-md transition-colors hover:bg-canvas focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
        >
          <Download className="size-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
