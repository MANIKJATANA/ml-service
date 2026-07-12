"use client";

import { ImageOff } from "lucide-react";
import { useRef, useState } from "react";

import { Spinner } from "@/components/ui/spinner";
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
  loading?: "spinner" | "square";
  fallbackText?: string;
}

/**
 * Loads a media's signed URL and renders it (decisions/0035): a lazy gate (`enabled`), a
 * one-shot re-mint on a 403 (expired URL mid-session), and a terminal fallback if either
 * the URL fetch OR the image itself fails — so nothing is left on a perpetual spinner.
 * Shared by the photo tile, the Lightbox, and the photo page.
 */
export function SignedImage({
  mediaId,
  alt,
  enabled = true,
  imgClassName,
  className,
  onDark = false,
  loading = "spinner",
  fallbackText = "Couldn't load this photo.",
}: SignedImageProps) {
  const { download, error, mutate } = useMediaDownload(mediaId, enabled);
  const [failed, setFailed] = useState(false);
  const retries = useRef(0);

  function onImgError() {
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
    return (
      <div className={cn("flex items-center justify-center", className)}>
        <Spinner className={cn("size-8", onDark ? "text-canvas" : "text-ink-muted")} />
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- signed URL, unknown aspect ratio
    <img src={download.download_url} alt={alt} onError={onImgError} className={imgClassName} />
  );
}
