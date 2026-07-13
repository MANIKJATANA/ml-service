"use client";

import { Images } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";

import { FilterChips } from "@/components/gallery/filter-chips";
import { GridSkeleton } from "@/components/gallery/grid-skeleton";
import { PhotoGrid } from "@/components/gallery/photo-grid";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useEvent } from "@/lib/hooks/use-events";
import {
  useEventMedia,
  useEventStudentMedia,
  useEventStudents,
} from "@/lib/hooks/use-galleries";

function AllPhotos({ eventId }: { eventId: string }) {
  const { media, isLoading, error, mutate } = useEventMedia(eventId);

  if (isLoading) return <GridSkeleton />;
  if (error) {
    return (
      <EmptyState
        role="alert"
        title="Couldn't load photos"
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
    return (
      <EmptyState
        icon={<Images className="size-8" aria-hidden="true" />}
        title="No photos yet"
        description="Upload photos to this event to see them here."
      />
    );
  }
  return <PhotoGrid mediaIds={media.map((m) => m.id)} />;
}

function EventStudentPhotos({ eventId, studentId }: { eventId: string; studentId: string }) {
  const { media, isLoading, error } = useEventStudentMedia(eventId, studentId);

  if (isLoading) return <GridSkeleton />;
  if (error) return <p className="text-body-sm text-ink-secondary">Couldn&apos;t load photos.</p>;
  if (!media || media.length === 0) {
    return <p className="text-body-sm text-ink-secondary">No photos for this student.</p>;
  }
  return <PhotoGrid mediaIds={media.map((m) => m.media_id)} />;
}

function ByStudent({ eventId }: { eventId: string }) {
  const { students, isLoading, error, mutate } = useEventStudents(eventId);
  const [picked, setPicked] = useState<string | null>(null);

  if (isLoading) return <GridSkeleton />;
  if (error) {
    return (
      <EmptyState
        role="alert"
        title="Couldn't load students"
        description="Something went wrong reaching the server."
        action={
          <Button variant="secondary" onClick={() => mutate()}>
            Retry
          </Button>
        }
      />
    );
  }
  if (!students || students.length === 0) {
    return (
      <EmptyState
        title="No students matched yet"
        description="Run distribution on this event — students who appear in its photos show up here."
      />
    );
  }

  const activeId = picked ?? students[0].student_id;
  return (
    <div className="flex flex-col gap-6">
      <FilterChips
        ariaLabel="Students"
        items={students.map((s) => ({ id: s.student_id, label: s.name, count: s.media_count }))}
        activeId={activeId}
        onSelect={setPicked}
      />
      <EventStudentPhotos eventId={eventId} studentId={activeId} />
    </div>
  );
}

export default function EventGalleryPage() {
  const { eventId } = useParams<{ eventId: string }>();
  const { event } = useEvent(eventId);

  return (
    <div className="flex flex-col gap-6">
      <Breadcrumb
        items={[
          { label: "Events", href: "/events" },
          { label: event?.name ?? "Event", href: `/events/${eventId}` },
          { label: "Gallery" },
        ]}
      />
      <PageHeader title="Gallery" description="Browse every photo, or see who appears in them." />

      <Tabs defaultValue="all">
        <TabsList>
          <TabsTrigger value="all">All photos</TabsTrigger>
          <TabsTrigger value="by-student">By student</TabsTrigger>
        </TabsList>
        <TabsContent value="all">
          <AllPhotos eventId={eventId} />
        </TabsContent>
        <TabsContent value="by-student">
          <ByStudent eventId={eventId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
