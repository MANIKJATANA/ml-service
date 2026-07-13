"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { ChevronLeft, ChevronRight, Download, X } from "lucide-react";
import { useEffect, useRef } from "react";

import { AppearanceList } from "@/components/gallery/appearance-list";
import { SignedImage } from "@/components/gallery/signed-image";
import { Button } from "@/components/ui/button";
import { useDownloadToDisk } from "@/lib/hooks/use-download-to-disk";
import { useMediaAppearances } from "@/lib/hooks/use-galleries";
import { useMediaDownload } from "@/lib/hooks/use-media-download";

interface LightboxProps {
  mediaIds: string[];
  index: number;
  onIndexChange: (index: number) => void;
  onClose: () => void;
  /** Show the "In this photo" panel. Off for students — the appearances endpoint is
   *  staff-only (gallery:view_all) and other students' names must not leak (0036). */
  showAppearances?: boolean;
}

/** Full-screen photo viewer: image + ←/→/Esc navigation, download, and who appears. */
export function Lightbox({
  mediaIds,
  index,
  onIndexChange,
  onClose,
  showAppearances = true,
}: LightboxProps) {
  const mediaId = mediaIds[index];
  const { download } = useMediaDownload(mediaId, true);
  const { appearances, isLoading: appsLoading } = useMediaAppearances(
    showAppearances ? mediaId : null,
  );
  const { downloading, onDownload } = useDownloadToDisk(mediaId, download);
  const contentRef = useRef<HTMLDivElement>(null);

  const canPrev = index > 0;
  const canNext = index < mediaIds.length - 1;

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "ArrowLeft" && canPrev) onIndexChange(index - 1);
      else if (e.key === "ArrowRight" && canNext) onIndexChange(index + 1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, canPrev, canNext, onIndexChange]);

  return (
    <DialogPrimitive.Root
      open
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-ink/80" />
        <DialogPrimitive.Content
          ref={contentRef}
          tabIndex={-1}
          onOpenAutoFocus={(e) => {
            // Deterministic initial focus — not the conditionally-present prev/next arrow.
            e.preventDefault();
            contentRef.current?.focus();
          }}
          className="fixed inset-0 z-50 flex flex-col focus:outline-none sm:flex-row"
        >
          <DialogPrimitive.Title className="sr-only">Photo viewer</DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">
            Use the left and right arrow keys to move between photos.
          </DialogPrimitive.Description>

          <div className="relative flex min-h-0 flex-1 items-center justify-center p-4 sm:p-8">
            <SignedImage
              key={mediaId}
              mediaId={mediaId}
              alt={`Photo ${index + 1} of ${mediaIds.length}`}
              onDark
              imgClassName="max-h-full max-w-full rounded-card object-contain"
            />

            {canPrev ? (
              <button
                type="button"
                onClick={() => onIndexChange(index - 1)}
                aria-label="Previous photo"
                className="absolute left-3 top-1/2 -translate-y-1/2 rounded-full bg-canvas/90 p-2 text-ink shadow-md transition-colors hover:bg-canvas focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <ChevronLeft className="size-5" />
              </button>
            ) : null}
            {canNext ? (
              <button
                type="button"
                onClick={() => onIndexChange(index + 1)}
                aria-label="Next photo"
                className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full bg-canvas/90 p-2 text-ink shadow-md transition-colors hover:bg-canvas focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <ChevronRight className="size-5" />
              </button>
            ) : null}
          </div>

          <aside className="flex max-h-[45vh] w-full shrink-0 flex-col gap-4 overflow-y-auto border-t border-hairline bg-canvas p-4 sm:max-h-none sm:w-80 sm:overflow-visible sm:border-l sm:border-t-0">
            <div className="flex items-center justify-between gap-2">
              <span
                aria-live="polite"
                aria-atomic="true"
                className="text-body-sm text-ink-secondary"
              >
                {index + 1} of {mediaIds.length}
              </span>
              <DialogPrimitive.Close
                aria-label="Close"
                className="rounded-button p-1 text-ink-muted transition-colors hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X className="size-5" />
              </DialogPrimitive.Close>
            </div>

            <Button onClick={onDownload} loading={downloading} disabled={!download}>
              <Download className="size-4" aria-hidden="true" />
              Download
            </Button>

            {showAppearances ? (
              <div className="flex flex-col gap-2">
                <h3 className="text-body-sm font-medium text-ink">In this photo</h3>
                <AppearanceList appearances={appearances} isLoading={appsLoading} />
              </div>
            ) : null}
          </aside>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
