"use client";

import { ImageOff } from "lucide-react";
import { useRef, useState } from "react";

import { Spinner } from "@/components/ui/spinner";
import type { MediaType, PhotoSize } from "@/lib/api/types";
import { useMediaDownload } from "@/lib/hooks/use-media-download";
import { cn } from "@/lib/utils";

interface SignedImageProps {
  mediaId: string;
  alt: string;
  enabled?: boolean;
  imgClassName?: string;
  /** Wrapper class for the loading / error states (e.g. to size them). */
  className?: string;
  onDark?: boolean;
  loading?: "spinner" | "square" | "block";
  fallbackText?: string;
  /** "image" (default) renders an <img>; "video" renders a <video> off the same signed URL
   *  (BP6). Callers thread the media's type so a video URL never lands in an <img>. */
  kind?: MediaType;
  /** For a video: `true` = a full <video controls> player (lightbox / detail page);
   *  `false` (default) = a muted, non-interactive first-frame poster for grid tiles. */
  asPlayer?: boolean;
  /** "thumb" (BP17) requests a downscaled image for tiles/avatars; "full" (default) is the
   *  original for the lightbox/detail. Ignored for video (always full — the browser paints
   *  the first-frame poster off the full URL). */
  size?: PhotoSize;
}

/**
 * Loads a media's signed URL and renders it (decisions/0035): a lazy gate (`enabled`), a
 * one-shot re-mint on a 403 (expired URL mid-session), and a terminal fallback if either
 * the URL fetch OR the media itself fails — so nothing is left on a perpetual spinner.
 * Renders an image or a video off the SAME signed URL (BP6, decisions/0043). Shared by the
 * photo tile, the Lightbox, and the photo page.
 */
export function SignedImage({
  mediaId,
  alt,
  enabled = true,
  imgClassName,
  className,
  onDark = false,
  loading = "spinner",
  fallbackText = "Couldn't load this media.",
  kind = "image",
  asPlayer = false,
  size = "full",
}: SignedImageProps) {
  // Video ignores `size` — it always mints the full URL (one cache key) and paints the
  // browser first-frame poster off it (BP6/BP17).
  const { download, error, mutate } = useMediaDownload(
    mediaId,
    enabled,
    kind === "video" ? "full" : size,
  );
  const [failed, setFailed] = useState(false);
  const retries = useRef(0);

  function onMediaError() {
    if (retries.current < 1) {
      retries.current += 1;
      void mutate(); // the signed URL may have expired mid-session — re-mint once
    } else {
      setFailed(true);
    }
  }

  if (failed || error) {
    return (
      <div
        className={cn(
          "flex flex-col items-center justify-center gap-1",
          onDark ? "text-canvas/80" : "text-ink-muted",
          className,
        )}
      >
        <ImageOff className="size-6" aria-hidden="true" />
        <span className="text-body-sm">{fallbackText}</span>
      </div>
    );
  }
  if (!download) {
    if (loading === "square") {
      return <div className={cn("aspect-square w-full animate-pulse bg-surface-2", className)} />;
    }
    if (loading === "block") {
      // Masonry placeholder: the caller supplies the aspect (unknown until the image
      // loads, then it takes its natural size and the column reflows).
      return <div className={cn("w-full animate-pulse bg-surface-2", className)} />;
    }
    return (
      <div className={cn("flex items-center justify-center", className)}>
        <Spinner className={cn("size-8", onDark ? "text-canvas" : "text-ink-muted")} />
      </div>
    );
  }
  if (kind === "video") {
    if (asPlayer) {
      return (
        <video
          src={download.download_url}
          controls
          playsInline
          onError={onMediaError}
          className={imgClassName}
          aria-label={alt || undefined}
        />
      );
    }
    // Grid poster: a muted, non-interactive first frame. The `#t=0.1` fragment nudges the
    // browser to paint a frame (a bare <video> can stay blank); `pointer-events-none` lets
    // the click fall through to the wrapping tile button, which opens the player.
    return (
      <video
        src={`${download.download_url}#t=0.1`}
        muted
        playsInline
        preload="metadata"
        tabIndex={-1}
        aria-hidden="true"
        onError={onMediaError}
        className={cn(imgClassName, "pointer-events-none")}
      />
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- signed URL, unknown aspect ratio
    <img src={download.download_url} alt={alt} onError={onMediaError} className={imgClassName} />
  );
}
