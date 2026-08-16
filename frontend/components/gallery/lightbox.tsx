"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { ChevronLeft, ChevronRight, Download, UserX, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { AppearanceEditor } from "@/components/gallery/appearance-editor";
import { AppearanceList } from "@/components/gallery/appearance-list";
import { DownloadHistory } from "@/components/gallery/download-history";
import { SignedImage } from "@/components/gallery/signed-image";
import { Button } from "@/components/ui/button";
import { useDownloadToDisk } from "@/lib/hooks/use-download-to-disk";
import { useMediaAppearances } from "@/lib/hooks/use-galleries";
import { useMediaDownload } from "@/lib/hooks/use-media-download";
import type { MediaType } from "@/lib/api/types";

interface LightboxProps {
  mediaIds: string[];
  /** Per-media type, aligned by index to `mediaIds` — a video renders a player (BP6). */
  mediaTypes?: MediaType[];
  /** Per-media "story" (event + date), aligned by index (BP20) — shown in the panel, folded
   *  into the image `alt`, and used to name the saved file. Undefined where not supplied. */
  mediaCaptions?: (string | undefined)[];
  index: number;
  onIndexChange: (index: number) => void;
  onClose: () => void;
  /** Show the "In this photo" panel. Off for students — the appearances endpoint is
   *  staff-only (gallery:view_all) and other students' names must not leak (0036). */
  showAppearances?: boolean;
  /** Staff (BP5): make the appearances panel EDITABLE — confirm/reject/undo each match +
   *  add a student the ML missed — for any photo, right here in the viewer. Requires
   *  `showAppearances`. Server-gated by `match:review` (decisions/0042). */
  canManageAppearances?: boolean;
  /** When set (the student surface, BP5), shows a "This isn't me" action for the current
   *  photo. The caller rejects the match + refreshes; the viewer closes after. */
  onNotMe?: (mediaId: string) => Promise<void>;
}

/** Full-screen photo viewer: image + ←/→/Esc navigation, download, and who appears. */
export function Lightbox({
  mediaIds,
  mediaTypes,
  mediaCaptions,
  index,
  onIndexChange,
  onClose,
  showAppearances = true,
  canManageAppearances = false,
  onNotMe,
}: LightboxProps) {
  const mediaId = mediaIds[index];
  const mediaType = mediaTypes?.[index] ?? "image";
  const caption = mediaCaptions?.[index];
  const { download } = useMediaDownload(mediaId, true);
  const { appearances, isLoading: appsLoading, mutate: mutateAppearances } =
    useMediaAppearances(showAppearances ? mediaId : null);
  const { downloading, onDownload } = useDownloadToDisk(mediaId, download, caption);
  const contentRef = useRef<HTMLDivElement>(null);
  const [notMeBusy, setNotMeBusy] = useState(false);

  async function handleNotMe() {
    if (!onNotMe) return;
    setNotMeBusy(true);
    try {
      await onNotMe(mediaId);
      onClose();
    } finally {
      setNotMeBusy(false);
    }
  }

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
          <DialogPrimitive.Title className="sr-only">Media viewer</DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">
            Use the left and right arrow keys to move between items.
          </DialogPrimitive.Description>

          <div className="relative flex min-h-0 flex-1 items-center justify-center p-4 sm:p-8">
            <SignedImage
              key={mediaId}
              mediaId={mediaId}
              kind={mediaType}
              asPlayer
              size="full"
              alt={
                caption
                  ? `${caption} (${index + 1} of ${mediaIds.length})`
                  : `${mediaType === "video" ? "Video" : "Photo"} ${index + 1} of ${mediaIds.length}`
              }
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

            {/* BP20: the photo's story — which event, when. */}
            {caption ? (
              <p className="-mt-1 text-body-sm font-medium text-ink">{caption}</p>
            ) : null}

            <Button onClick={onDownload} loading={downloading} disabled={!download}>
              <Download className="size-4" aria-hidden="true" />
              Download
            </Button>

            {/* School-admin-only download history (BP8b); the staff surface only. */}
            {showAppearances ? <DownloadHistory mediaId={mediaId} /> : null}

            {onNotMe ? (
              <Button
                variant="secondary"
                onClick={handleNotMe}
                loading={notMeBusy}
                disabled={notMeBusy}
              >
                <UserX className="size-4" aria-hidden="true" />
                This isn&apos;t me
              </Button>
            ) : null}

            {showAppearances ? (
              <div className="flex flex-col gap-2">
                <h3 className="text-body-sm font-medium text-ink">
                  In this {mediaType === "video" ? "video" : "photo"}
                </h3>
                {canManageAppearances ? (
                  <AppearanceEditor
                    mediaId={mediaId}
                    appearances={appearances}
                    isLoading={appsLoading}
                    onChanged={() => mutateAppearances()}
                  />
                ) : (
                  <AppearanceList appearances={appearances} isLoading={appsLoading} />
                )}
              </div>
            ) : null}
          </aside>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
