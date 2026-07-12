"use client";

import { Download } from "lucide-react";
import { useParams } from "next/navigation";

import { AppearanceList } from "@/components/gallery/appearance-list";
import { SignedImage } from "@/components/gallery/signed-image";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { isApiError } from "@/lib/api/errors";
import { useDownloadToDisk } from "@/lib/hooks/use-download-to-disk";
import { useMedia, useMediaAppearances } from "@/lib/hooks/use-galleries";
import { useMediaDownload } from "@/lib/hooks/use-media-download";

export default function PhotoDetailPage() {
  const { mediaId } = useParams<{ mediaId: string }>();
  const { media, isLoading, error } = useMedia(mediaId);
  const { download } = useMediaDownload(mediaId, true);
  const { appearances, isLoading: appsLoading } = useMediaAppearances(mediaId);
  const { downloading, onDownload } = useDownloadToDisk(mediaId, download);

  const notFound = isApiError(error) && error.status === 404;

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }
  if (error || !media) {
    return (
      <EmptyState
        title={notFound ? "Photo not found" : "Couldn't load photo"}
        description={
          notFound ? "It may have been removed." : "Something went wrong reaching the server."
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <Breadcrumb
        items={[
          { label: "Events", href: "/events" },
          { label: "Gallery", href: `/events/${media.event_id}/gallery` },
          { label: "Photo" },
        ]}
      />
      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <Card className="flex items-center justify-center overflow-hidden bg-surface-2 p-2">
          <SignedImage
            mediaId={mediaId}
            alt="Event photo"
            className="h-64 w-full"
            imgClassName="max-h-[70vh] w-auto rounded-button object-contain"
          />
        </Card>
        <Card className="flex h-fit flex-col gap-4 p-6">
          <Button onClick={onDownload} loading={downloading} disabled={!download}>
            <Download className="size-4" aria-hidden="true" />
            Download
          </Button>
          <div className="flex flex-col gap-2">
            <h2 className="text-body-sm font-medium text-ink">In this photo</h2>
            <AppearanceList appearances={appearances} isLoading={appsLoading} />
          </div>
        </Card>
      </div>
    </div>
  );
}
