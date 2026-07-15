"use client";

import { CheckCircle2, Clock, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { mutate as globalMutate } from "swr";

import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { MultiFileDropzone } from "@/components/ui/multi-file-dropzone";
import { PageHeader } from "@/components/ui/page-header";
import { ProgressBar } from "@/components/ui/progress-bar";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { isApiError } from "@/lib/api/errors";
import { useEvent } from "@/lib/hooks/use-events";
import { type UploadStatus, useMediaUpload } from "@/lib/hooks/use-media-upload";

function UploadStatusIcon({ status }: { status: UploadStatus }) {
  if (status === "done") {
    return <CheckCircle2 className="size-4 shrink-0 text-success-strong" aria-hidden="true" />;
  }
  if (status === "error") {
    return <XCircle className="size-4 shrink-0 text-error-strong" aria-hidden="true" />;
  }
  if (status === "uploading") {
    return <Spinner className="size-4 shrink-0 text-accent-hover" />;
  }
  return <Clock className="size-4 shrink-0 text-ink-muted" aria-hidden="true" />;
}

export default function EventUploadPage() {
  const { eventId } = useParams<{ eventId: string }>();
  const router = useRouter();
  const { event, isLoading, error } = useEvent(eventId);
  const { items, isUploading, summary, add } = useMediaUpload(eventId);

  const notFound = isApiError(error) && error.status === 404;
  const isArchived = event?.status === "archived";

  function backToEvent() {
    // Refresh the event's photo status/roster so the detail page shows the new counts.
    void globalMutate(`events/${eventId}/status`);
    void globalMutate(`events/${eventId}/media`);
    router.push(`/events/${eventId}`);
  }

  return (
    <div className="flex flex-col gap-6">
      <Breadcrumb
        items={[
          { label: "Events", href: "/events" },
          { label: event?.name ?? "Event", href: `/events/${eventId}` },
          { label: "Upload" },
        ]}
      />

      {isLoading ? (
        <Card className="flex flex-col gap-3 p-6">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-28 w-full" />
        </Card>
      ) : error || !event ? (
        <EmptyState
          role="alert"
          title={notFound ? "Event not found" : "Couldn't load event"}
          description={
            notFound ? "It may have been removed." : "Something went wrong reaching the server."
          }
        />
      ) : isArchived ? (
        <EmptyState
          title="Event is archived"
          description="Restore the event to upload photos."
          action={
            <Link
              href={`/events/${eventId}`}
              className={buttonVariants({ variant: "secondary" })}
            >
              Back to event
            </Link>
          }
        />
      ) : (
        <>
          <PageHeader
            title="Upload media"
            description={`Add photos and videos to “${event.name}”. Run distribution from the event once they're in.`}
          />

          <Card className="flex flex-col gap-4 p-6">
            <MultiFileDropzone
              onFiles={add}
              disabled={isUploading}
              accept="image/*,video/*"
              label="Photos & videos"
              hint="Photos and videos — select as many as you like."
            />

            {items.length > 0 ? (
              <div className="flex flex-col gap-2">
                <span aria-live="polite" className="text-body-sm text-ink-secondary">
                  {isUploading
                    ? `Uploading… ${summary.done + summary.failed} of ${summary.total}`
                    : `${summary.done} uploaded${summary.failed > 0 ? `, ${summary.failed} failed` : ""}`}
                </span>
                <ul className="flex flex-col divide-y divide-hairline rounded-button border border-hairline">
                  {items.map((item) => (
                    <li key={item.id} className="flex items-center gap-3 px-3 py-2">
                      <UploadStatusIcon status={item.status} />
                      <span
                        className="min-w-0 flex-1 truncate text-body-sm text-ink"
                        title={item.name}
                      >
                        {item.name}
                      </span>
                      {item.status === "uploading" ? (
                        <span className="w-24 shrink-0">
                          <ProgressBar value={item.progress} label={`Uploading ${item.name}`} />
                        </span>
                      ) : item.status === "error" ? (
                        <span className="shrink-0 text-body-sm text-error-strong">
                          {item.error}
                        </span>
                      ) : (
                        <span className="shrink-0 text-body-sm text-ink-secondary">
                          {item.status === "done" ? "Uploaded" : "Queued"}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </Card>

          <div className="flex justify-end">
            <Button
              variant={summary.done > 0 ? "primary" : "secondary"}
              onClick={backToEvent}
              disabled={isUploading}
            >
              {isUploading ? "Uploading…" : "Back to event"}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
