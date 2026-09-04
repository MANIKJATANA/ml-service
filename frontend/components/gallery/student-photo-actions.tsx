"use client";

import { Download, Shuffle, SquareCheck } from "lucide-react";
import { type ReactNode, useCallback, useMemo, useState } from "react";

import { PhotoGrid } from "@/components/gallery/photo-grid";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { SendPhotosButton } from "@/components/whatsapp/send-photos-button";
import type { GalleryMediaResponse } from "@/lib/api/types";
import { useDownloadAll } from "@/lib/hooks/use-download-all";

const DEFAULT_RANDOM = 10; // the default "select random N" count

/** Pick up to `n` random media ids (Fisher–Yates partial shuffle; browser `Math.random`). */
function pickRandomIds(media: GalleryMediaResponse[], n: number): Set<string> {
  const ids = media.map((m) => m.media_id);
  for (let i = ids.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [ids[i], ids[j]] = [ids[j], ids[i]];
  }
  return new Set(ids.slice(0, Math.max(0, Math.min(n, ids.length))));
}

/** Download a GIVEN set of a student's photos as ONE zip — reuses the download entitlement (both
 *  staff roles hold `gallery:view_all`) + the streaming `useDownloadAll`, no backend change (BP26
 *  v1 / decisions/0081: staff download → share). `mediaList` is the ACTIVE target (selection or
 *  whole view) so the zip re-keys when it changes; `zipEntryFor` builds each photo's folder/name. */
function PhotoDownloadButton({
  mediaList,
  zipEntryFor,
  zipName,
}: {
  mediaList: GalleryMediaResponse[];
  zipEntryFor: (media: GalleryMediaResponse, index: number) => string;
  zipName: string;
}) {
  const { toast } = useToast();
  const mediaIds = useMemo(() => mediaList.map((m) => m.media_id), [mediaList]);
  const entryBase = useCallback(
    (i: number) => zipEntryFor(mediaList[i], i),
    [mediaList, zipEntryFor],
  );
  const { busy, done, total, cap, onDownloadAll } = useDownloadAll(mediaIds, {
    entryBase,
    zipName,
  });

  async function handleDownload() {
    try {
      const { saved, capped, cancelled } = await onDownloadAll();
      if (cancelled) return; // dismissed the save dialog — silent, not an error
      // Copy mirrors the sibling staff surfaces (student detail + the event-gallery download).
      if (saved === 0) {
        toast("Couldn't download the photos. Please try again.", "error");
      } else if (capped) {
        toast(
          `Saved the first ${cap} of ${total} photos. To get the rest, open this page in desktop Chrome or Edge.`,
          "info",
          { sticky: true },
        );
      } else if (saved < total) {
        toast(
          `Saved ${saved} of ${total} photos — ${total - saved} couldn't be saved right now. Try again.`,
          "info",
          { sticky: true },
        );
      } else {
        toast(`Downloaded ${total} ${total === 1 ? "photo" : "photos"}.`, "success");
      }
    } catch {
      toast("Couldn't prepare the download. Please try again.", "error");
    }
  }

  return (
    <div className="flex items-center gap-3">
      <Button
        variant="secondary"
        size="sm"
        onClick={handleDownload}
        loading={busy}
        disabled={busy || total === 0}
      >
        <Download className="size-4" aria-hidden="true" />
        {busy ? "Preparing…" : "Download"}
      </Button>
      {/* SR-only progress (a *visible* per-tick live region would announce on every photo; the
          button-label flip covers sighted users). */}
      {busy ? (
        <span className="sr-only" aria-live="polite">
          Preparing {done} of {total} photos
        </span>
      ) : null}
    </div>
  );
}

/** The shared select/send/download UX for one student's photos (decisions/0100 + its event-gallery
 *  follow-on). A "Select photos" toggle enters SELECT mode — tap-to-select + "Select all" /
 *  "Select random N" / "Clear" — and **Send + Download target the SELECTION**; in browse mode they
 *  target the **whole `media`** and tiles open the lightbox. Used by BOTH the student-detail
 *  "Appears in" section (per-view) and the event-gallery "By student" tab (per-event). The caller
 *  loads `media` (already the effective set) + owns any title/filter above it, and supplies the zip
 *  naming. `resetKey` clears the selection when the source changes (a view/student switch) so a
 *  send/download can never act on another view's photos. */
export function StudentPhotoActions({
  media,
  studentId,
  studentName,
  optedIn,
  hasNumber,
  resetKey,
  zipEntryFor,
  zipName,
  captionOf,
  canManageAppearances = true,
  leftHeader,
}: {
  media: GalleryMediaResponse[];
  studentId: string;
  studentName: string;
  optedIn: boolean;
  hasNumber: boolean;
  /** Clears the selection when it changes (a view/student switch) — stale-safe. */
  resetKey: string;
  zipEntryFor: (media: GalleryMediaResponse, index: number) => string;
  zipName: string;
  /** Optional per-photo caption (the student-detail "All" view captions by event). */
  captionOf?: (media: GalleryMediaResponse) => string | undefined;
  canManageAppearances?: boolean;
  /** Optional context node shown left of the "Select photos" toggle (e.g. a photo count). */
  leftHeader?: ReactNode;
}) {
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [randomN, setRandomN] = useState(DEFAULT_RANDOM);

  // Clear the selection when the source changes (view/student switch) — stale-safe;
  // adjust-state-during-render, so a selection can never act on a different source's photos.
  const [prevKey, setPrevKey] = useState(resetKey);
  if (prevKey !== resetKey) {
    setPrevKey(resetKey);
    setSelected(new Set());
  }

  // What the actions act on: the selection (Select mode) or the whole view (Browse).
  const targetMedia = useMemo(
    () => (selectMode ? media.filter((m) => selected.has(m.media_id)) : media),
    [media, selectMode, selected],
  );
  const targetIds = useMemo(() => targetMedia.map((m) => m.media_id), [targetMedia]);
  const viewCount = media.length;

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function exitSelect() {
    setSelectMode(false);
    setSelected(new Set());
  }

  const items = media.map((m) => ({
    id: m.media_id,
    mediaType: m.media_type,
    hasThumbnail: m.has_thumbnail,
    caption: captionOf?.(m),
  }));

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* An empty span keeps the toggle right-aligned (justify-between) when no header is given. */}
        {leftHeader ?? <span />}
        {selectMode ? (
          <Button variant="secondary" size="sm" onClick={exitSelect}>
            Done
          </Button>
        ) : (
          <Button variant="secondary" size="sm" onClick={() => setSelectMode(true)}>
            <SquareCheck className="size-4" aria-hidden="true" />
            Select photos
          </Button>
        )}
      </div>

      {/* In Select mode, build the target — all of this view, a random sample, or manual taps. */}
      {selectMode ? (
        <div className="flex flex-wrap items-center gap-2 rounded-button bg-surface px-3 py-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setSelected(new Set(media.map((m) => m.media_id)))}
            disabled={viewCount === 0}
          >
            Select all ({viewCount})
          </Button>
          <div className="flex items-center gap-1.5">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setSelected(pickRandomIds(media, randomN))}
              disabled={viewCount === 0}
            >
              <Shuffle className="size-4" aria-hidden="true" />
              Select random
            </Button>
            <input
              type="number"
              min={1}
              max={Math.max(1, viewCount)}
              // Show a value that's honest for the current view (never > its count) while `randomN`
              // preserves intent for a bigger view; `pickRandomIds` also clamps.
              value={Math.min(randomN, Math.max(1, viewCount))}
              onChange={(e) => setRandomN(Math.max(1, Number(e.target.value) || 1))}
              aria-label="Number of random photos"
              className="h-8 w-16 rounded-button border border-hairline bg-canvas px-2 text-body-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setSelected(new Set())}
            disabled={selected.size === 0}
          >
            Clear
          </Button>
        </div>
      ) : null}

      {/* The grid — Select mode toggles tiles; Browse opens the lightbox (+ appearance editing). */}
      {selectMode ? (
        <PhotoGrid
          items={items}
          selectionMode
          selectedIds={selected}
          onToggleSelect={toggleSelect}
          showAppearances={false}
        />
      ) : (
        <PhotoGrid items={items} canManageAppearances={canManageAppearances} />
      )}

      {/* Floating action capsule (the picked design) — a compact centered pill that FLOATS above
          the grid while scrolling (sticky), so Send/Download stay reachable without scrolling past a
          long grid. Scroll behaviour: the wrapper is the last child + `sticky bottom-4`, so it
          reserves its space in flow (nothing is permanently hidden) and settles below the grid at
          max scroll; the wrapper is `pointer-events-none` (grid taps pass through) while the pill
          itself is `pointer-events-auto`. `z-10` keeps it above tiles, below the lightbox (z-50).
          The count sits in the pill (what you're about to act on); the buttons are compact. */}
      <div className="pointer-events-none sticky bottom-4 z-10 flex justify-center">
        <div
          className="pointer-events-auto flex items-center gap-2 rounded-full border border-hairline bg-canvas py-2 pl-4 pr-2"
          style={{ boxShadow: "0 10px 30px -8px rgba(15, 23, 42, 0.28)" }}
        >
          <span role="status" className="whitespace-nowrap text-body-sm font-medium text-ink">
            {selectMode
              ? `${selected.size} selected`
              : `${media.length} ${media.length === 1 ? "photo" : "photos"}`}
          </span>
          <SendPhotosButton
            studentId={studentId}
            studentName={studentName}
            mediaIds={targetIds}
            optedIn={optedIn}
            hasNumber={hasNumber}
            size="sm"
            compact
          />
          <PhotoDownloadButton
            mediaList={targetMedia}
            zipEntryFor={zipEntryFor}
            zipName={zipName}
          />
        </div>
      </div>
    </div>
  );
}
