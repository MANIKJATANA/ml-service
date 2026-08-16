"use client";

import { Download, Images, Sparkles } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { EventFilter } from "@/components/gallery/event-filter";
import { GridSkeleton } from "@/components/gallery/grid-skeleton";
import { PhotoGrid } from "@/components/gallery/photo-grid";
import { Button, buttonVariants } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { useToast } from "@/components/ui/toast";
import { markNotificationSeen, reportNotMe } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { MyNotificationEvent } from "@/lib/api/types";
import { formatEventDate, toISODate } from "@/lib/events/calendar";
import { useDownloadAll } from "@/lib/hooks/use-download-all";
import { useMyEvents, useMyMedia } from "@/lib/hooks/use-my-gallery";
import { useMyNotifications } from "@/lib/hooks/use-my-notifications";
import { sanitizeFilename } from "@/lib/utils";

/** event_id → its display name + date, for the photo "story" + saved-file naming (BP20). */
type EventMeta = Map<string, { name: string; date: string | null }>;

// Cap the "new since your last visit" banner so a long absence doesn't bury the photos.
const MAX_BANNER_EVENTS = 6;

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** The photo area: its own loading / error / empty / grid states, so the hero stays put
 *  while switching event filters. */
function PhotoArea({
  eventId,
  eventMeta,
  onLoaded,
}: {
  eventId: string | null;
  eventMeta: EventMeta;
  onLoaded: () => void;
}) {
  const { media, isLoading, error, mutate } = useMyMedia(eventId);
  const { toast } = useToast();

  // Newest-first (BP20): the backend serves oldest-first (created_at asc) and the payload has
  // no timestamp to sort by, so reversing the fetch order = newest-uploaded first.
  const ordered = useMemo(() => (media ? [...media].reverse() : []), [media]);

  // Fire once when the first media load SUCCEEDS — drives the parent's arrive-to-clear.
  // Deliberately success-only: if photos couldn't load, the student hasn't seen them, so we
  // don't clear the "new" flag (it clears on the next visit that actually renders photos — or
  // when the in-page Retry succeeds). Marking seen on error would wrongly dismiss unseen photos.
  const fired = useRef(false);
  useEffect(() => {
    if (!fired.current && !isLoading && media) {
      fired.current = true;
      onLoaded();
    }
  }, [isLoading, media, onLoaded]);

  const captionOf = useCallback(
    (evId: string): string | undefined => {
      const meta = eventMeta.get(evId);
      if (!meta) return undefined;
      const date = formatEventDate(meta.date);
      return date ? `${meta.name} · ${date}` : meta.name;
    },
    [eventMeta],
  );

  const items = useMemo(
    () =>
      ordered.map((m) => ({
        id: m.media_id,
        mediaType: m.media_type,
        hasThumbnail: m.has_thumbnail,
        caption: captionOf(m.event_id),
      })),
    [ordered, captionOf],
  );
  const mediaIds = useMemo(() => ordered.map((m) => m.media_id), [ordered]);

  // Name the saved zip + entries by event/date so a big save isn't an anonymous pile (BP20).
  // `new Date()` in a lazy initializer runs once at mount, not on every render.
  const [zipStamp] = useState(() => toISODate(new Date()));
  const entryBase = useCallback(
    (i: number) => {
      const m = ordered[i];
      const meta = m ? eventMeta.get(m.event_id) : undefined;
      const folder = (meta && sanitizeFilename(meta.name)) || "Photos";
      const datePart = meta?.date ?? "photo";
      return `${folder}/${datePart}-${String(i + 1).padStart(3, "0")}`;
    },
    [ordered, eventMeta],
  );
  const { busy, done, total, cap, onDownloadAll } = useDownloadAll(mediaIds, {
    entryBase,
    zipName: `my-photos-${zipStamp}.zip`,
  });

  async function handleDownloadAll() {
    try {
      const { saved, capped } = await onDownloadAll();
      if (capped) {
        toast(
          `Saved the first ${cap} of ${total} photos. To get them all, filter by an event and download each one, or open this page in desktop Chrome or Edge.`,
          "info",
          { sticky: true },
        );
      } else if (saved > 0 && saved < total) {
        toast(
          `Saved ${saved} of ${total} photos — ${total - saved} couldn't be saved right now. Try downloading again.`,
          "info",
          { sticky: true },
        );
      }
    } catch {
      toast("Couldn't prepare your download. Please try again.", "error");
    }
  }

  async function handleNotMe(id: string) {
    try {
      await reportNotMe(id);
      await mutate(); // drop the photo from the grid
      toast("Removed from your photos.", "success");
    } catch (err) {
      toast(isApiError(err) ? err.message : "Couldn't update. Please try again.", "error");
    }
  }

  if (isLoading) return <GridSkeleton variant="masonry" />;
  if (error) {
    return (
      <EmptyState
        role="alert"
        title="Couldn't load your photos"
        description="Something went wrong reaching the server."
        action={
          <Button variant="secondary" onClick={() => mutate()}>
            Retry
          </Button>
        }
      />
    );
  }
  if (ordered.length === 0) {
    return <p className="text-body-sm text-ink-secondary">No photos to show here.</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <span className="text-body-sm text-ink-muted">
          {plural(ordered.length, "photo", "photos")}
        </span>
        <Button variant="secondary" size="sm" onClick={handleDownloadAll} loading={busy} disabled={busy}>
          <Download className="size-4" aria-hidden="true" />
          {busy ? `Preparing ${done}/${total}…` : "Download all"}
        </Button>
        {busy ? (
          <span className="sr-only" aria-live="polite">
            Preparing {done} of {total} photos
          </span>
        ) : null}
      </div>
      {/* Appearances hidden for students: that endpoint is staff-only and other students'
          names must not leak (decisions/0036). "This isn't me" (BP5) lets them remove a
          wrongly-matched photo. */}
      <PhotoGrid
        items={items}
        variant="masonry"
        showAppearances={false}
        onNotMe={handleNotMe}
      />
    </div>
  );
}

export default function MyPhotosPage() {
  const { events, isLoading, error, mutate } = useMyEvents();
  const { notifications, mutate: mutateNotifications } = useMyNotifications();
  const [selected, setSelected] = useState(""); // "" = all events

  // Newest-first for the chips + the event lookup (BP20) — reverse a copy of the asc payload.
  const eventsNewestFirst = useMemo(() => (events ? [...events].reverse() : []), [events]);
  const totalPhotos = eventsNewestFirst.reduce((s, e) => s + e.media_count, 0);
  const eventMeta = useMemo<EventMeta>(() => {
    const m: EventMeta = new Map();
    for (const e of eventsNewestFirst) m.set(e.event_id, { name: e.name, date: e.event_date });
    return m;
  }, [eventsNewestFirst]);

  // Derived, not effect-reconciled (BP11a stale-safe): a filter on a since-removed event
  // silently falls back to "All" rather than stranding the grid empty.
  const activeEventId = selected && eventMeta.has(selected) ? selected : "";

  // Snapshot this visit's unseen events for the banner (a one-visit highlight), captured once
  // — independent of the mark-seen below, so it persists after the badge clears.
  const [newEvents, setNewEvents] = useState<MyNotificationEvent[]>([]);
  const snapped = useRef(false);
  useEffect(() => {
    if (snapped.current || !notifications) return;
    snapped.current = true;
    setNewEvents(notifications.events.filter((e) => e.unseen));
  }, [notifications]);

  // Arrive-to-clear (BP20): mark announced events seen only AFTER the photos render — not on
  // mount, before anything was seen. Fires once, when both notifications and the first photo
  // load have resolved (whichever completes last).
  const [photosLoaded, setPhotosLoaded] = useState(false);
  const cleared = useRef(false);
  useEffect(() => {
    if (cleared.current || !notifications || !photosLoaded) return;
    cleared.current = true;
    const unseen = notifications.events.filter((e) => e.unseen).map((e) => e.event_id);
    if (unseen.length > 0) {
      void (async () => {
        await Promise.allSettled(unseen.map((id) => markNotificationSeen(id)));
        void mutateNotifications();
      })();
    }
  }, [notifications, photosLoaded, mutateNotifications]);

  const onPhotosLoaded = useCallback(() => setPhotosLoaded(true), []);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <div className="h-9 w-48 animate-pulse rounded bg-surface-2" />
        <GridSkeleton variant="masonry" />
      </div>
    );
  }

  if (error) {
    return (
      <EmptyState
        role="alert"
        title="Couldn't load your photos"
        description="Something went wrong reaching the server."
        action={
          <Button variant="secondary" onClick={() => mutate()}>
            Retry
          </Button>
        }
      />
    );
  }

  if (eventsNewestFirst.length === 0) {
    return (
      <EmptyState
        icon={<Images className="size-8" aria-hidden="true" />}
        title="No photos yet"
        description="When you appear in your school's event photos, they'll show up here — visible only to you and your school's staff."
        action={
          <Link href="/how-matching-works" className={buttonVariants({ variant: "secondary" })}>
            How photo matching works
          </Link>
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-display-xl text-ink">My Photos</h1>
        <p className="text-body text-ink-secondary">
          You&apos;re in {plural(totalPhotos, "photo", "photos")} from{" "}
          {plural(eventsNewestFirst.length, "event", "events")} — private to you and your
          school&apos;s staff. Other students only ever see photos they&apos;re in too.
        </p>
        <Link
          href="/how-matching-works"
          className="w-fit rounded text-body-sm text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          How photo matching works
        </Link>
        {newEvents.length > 0 ? (
          // A labelled group of filter shortcuts — NOT a live region (it wraps interactive
          // buttons and never updates after the one-visit snapshot). Capped so a long absence
          // doesn't bury the photos under a wall of chips (mirrors EventFilter's own limit).
          <div
            role="group"
            aria-label="New since your last visit"
            className="mt-1 flex flex-wrap items-center gap-2 rounded-card bg-accent/10 px-3 py-2 text-body-sm text-accent-dark"
          >
            <Sparkles className="size-4 shrink-0" aria-hidden="true" />
            <span className="font-medium">New since your last visit:</span>
            {newEvents.slice(0, MAX_BANNER_EVENTS).map((e) => (
              <button
                key={e.event_id}
                type="button"
                onClick={() => setSelected(e.event_id)}
                aria-label={`View ${e.name} — ${plural(e.media_count, "new photo", "new photos")}`}
                className="rounded-full border border-accent/30 bg-canvas px-2.5 py-0.5 font-medium text-accent-dark transition-colors hover:bg-accent/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {e.name}
                <span className="ml-1 tabular-nums" aria-hidden="true">
                  {e.media_count}
                </span>
              </button>
            ))}
            {newEvents.length > MAX_BANNER_EVENTS ? (
              <span className="text-ink-muted">+{newEvents.length - MAX_BANNER_EVENTS} more</span>
            ) : null}
          </div>
        ) : null}
      </header>

      {eventsNewestFirst.length > 1 ? (
        <EventFilter
          events={eventsNewestFirst}
          totalPhotos={totalPhotos}
          activeId={activeEventId}
          onSelect={setSelected}
        />
      ) : null}

      <PhotoArea eventId={activeEventId || null} eventMeta={eventMeta} onLoaded={onPhotosLoaded} />
    </div>
  );
}
