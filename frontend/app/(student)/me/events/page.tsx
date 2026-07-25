"use client";

import { Download, Images, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { FilterChips } from "@/components/gallery/filter-chips";
import { GridSkeleton } from "@/components/gallery/grid-skeleton";
import { PhotoGrid } from "@/components/gallery/photo-grid";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { useToast } from "@/components/ui/toast";
import { markNotificationSeen, reportNotMe } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import { useDownloadAll } from "@/lib/hooks/use-download-all";
import { useMyEvents, useMyMedia } from "@/lib/hooks/use-my-gallery";
import { useMyNotifications } from "@/lib/hooks/use-my-notifications";

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** The photo area: its own loading / error / empty / grid states, so the hero stays put
 *  while switching event filters. */
function PhotoArea({ eventId }: { eventId: string | null }) {
  const { media, isLoading, error, mutate } = useMyMedia(eventId);
  const { toast } = useToast();
  const mediaIds = useMemo(() => (media ?? []).map((m) => m.media_id), [media]);
  const items = useMemo(
    () =>
      (media ?? []).map((m) => ({
        id: m.media_id,
        mediaType: m.media_type,
        hasThumbnail: m.has_thumbnail,
      })),
    [media],
  );
  const { busy, done, total, onDownloadAll } = useDownloadAll(mediaIds);

  async function handleDownloadAll() {
    try {
      const saved = await onDownloadAll();
      if (saved > 0 && saved < total) {
        toast(
          `Downloaded ${saved} of ${total} photos — ${total - saved} couldn't be saved. Try again to get the rest.`,
          "info",
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
  if (!media || media.length === 0) {
    return <p className="text-body-sm text-ink-secondary">No photos to show here.</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <span className="text-body-sm text-ink-muted">{plural(media.length, "photo", "photos")}</span>
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

  const totalPhotos = (events ?? []).reduce((s, e) => s + e.media_count, 0);

  // Landing on "My Photos" IS seeing them: mark the announced events seen ON LOAD (once) so
  // it sticks across a browser refresh (an unmount handler wouldn't finish the POST before a
  // reload). Snapshot the tally into state so this visit's banner persists while the nav
  // badge clears — here, on refresh, and on another device.
  const [newCount, setNewCount] = useState(0);
  const marked = useRef(false);
  useEffect(() => {
    if (marked.current || !notifications) return;
    marked.current = true;
    const unseen = notifications.events.filter((e) => e.unseen).map((e) => e.event_id);
    void (async () => {
      setNewCount(notifications.unseen_count);
      if (unseen.length > 0) {
        await Promise.allSettled(unseen.map((id) => markNotificationSeen(id)));
        void mutateNotifications();
      }
    })();
  }, [notifications, mutateNotifications]);

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

  if (!events || events.length === 0) {
    return (
      <EmptyState
        icon={<Images className="size-8" aria-hidden="true" />}
        title="No photos yet"
        description="When you appear in your school's event photos, they'll show up here — privately, just for you."
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-display-lg text-ink">Your photos</h1>
        <p className="text-body text-ink-secondary">
          You&apos;re in {plural(totalPhotos, "photo", "photos")} from{" "}
          {plural(events.length, "event", "events")}. Only you can see these.
        </p>
        {newCount > 0 ? (
          <p
            role="status"
            className="mt-1 inline-flex w-fit items-center gap-2 rounded-full bg-accent/10 px-3 py-1 text-body-sm text-accent-dark"
          >
            <Sparkles className="size-4" aria-hidden="true" />
            New photos from {plural(newCount, "event", "events")} since your last visit
          </p>
        ) : null}
      </header>

      {events.length > 1 ? (
        <FilterChips
          ariaLabel="Events"
          activeId={selected}
          onSelect={setSelected}
          items={[
            { id: "", label: "All events", count: totalPhotos },
            ...events.map((e) => ({ id: e.event_id, label: e.name, count: e.media_count })),
          ]}
        />
      ) : null}

      <PhotoArea eventId={selected || null} />
    </div>
  );
}
