"use client";

import { Images } from "lucide-react";
import { useState } from "react";

import { FilterChips } from "@/components/gallery/filter-chips";
import { GridSkeleton } from "@/components/gallery/grid-skeleton";
import { PhotoGrid } from "@/components/gallery/photo-grid";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { useMyEvents, useMyMedia } from "@/lib/hooks/use-my-gallery";

const DESCRIPTION = "Photos you appear in from your school's events.";

function MyPhotos({ eventId }: { eventId: string | null }) {
  const { media, isLoading, error, mutate } = useMyMedia(eventId);

  if (isLoading) return <GridSkeleton />;
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
    return <p className="text-body-sm text-ink-secondary">No photos to show.</p>;
  }
  // No appearances panel for students: that endpoint is staff-only, and other students'
  // names must not leak (decisions/0036).
  return <PhotoGrid mediaIds={media.map((m) => m.media_id)} showAppearances={false} />;
}

export default function MyPhotosPage() {
  const { events, isLoading, error, mutate } = useMyEvents();
  const [selected, setSelected] = useState(""); // "" = all events

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="My Photos" description={DESCRIPTION} />

      {isLoading ? (
        <GridSkeleton />
      ) : error ? (
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
      ) : !events || events.length === 0 ? (
        <EmptyState
          icon={<Images className="size-8" aria-hidden="true" />}
          title="No photos yet"
          description="When you appear in your school's event photos, they'll show up here."
        />
      ) : (
        <>
          {events.length > 1 ? (
            <FilterChips
              ariaLabel="Events"
              activeId={selected}
              onSelect={setSelected}
              items={[
                { id: "", label: "All events", count: events.reduce((s, e) => s + e.media_count, 0) },
                ...events.map((e) => ({ id: e.event_id, label: e.name, count: e.media_count })),
              ]}
            />
          ) : null}
          <MyPhotos eventId={selected || null} />
        </>
      )}
    </div>
  );
}
