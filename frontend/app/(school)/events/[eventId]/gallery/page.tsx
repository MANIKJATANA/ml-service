"use client";

import { Images } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { mutate as globalMutate } from "swr";

import { FilterChips } from "@/components/gallery/filter-chips";
import { GridSkeleton } from "@/components/gallery/grid-skeleton";
import { PhotoGrid } from "@/components/gallery/photo-grid";
import { SignedImage } from "@/components/gallery/signed-image";
import { StudentRefAvatar } from "@/components/gallery/student-ref-avatar";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { batchReview } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { MediaType } from "@/lib/api/types";
import { useDownloadAll } from "@/lib/hooks/use-download-all";
import { useEvent } from "@/lib/hooks/use-events";
import {
  useEventMedia,
  useEventReview,
  useEventStudentMedia,
  useEventStudents,
} from "@/lib/hooks/use-galleries";
import { cn } from "@/lib/utils";

function AllPhotos({ eventId }: { eventId: string }) {
  const { items, total, isLoading, isLoadingMore, error, reachedEnd, loadMore, mutate } =
    useEventMedia(eventId);
  const { toast } = useToast();
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const selectedIds = [...selected];
  const { busy, done, total: dlTotal, onDownloadAll } = useDownloadAll(selectedIds);
  const isInitialLoading = isLoading && items.length === 0;

  function exitSelect() {
    setSelectMode(false);
    setSelected(new Set());
  }
  function toggleSelect(id: string) {
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  async function downloadSelected() {
    if (selectedIds.length === 0) return;
    try {
      const { saved } = await onDownloadAll();
      if (saved > 0) {
        toast(`Downloaded ${saved} ${saved === 1 ? "photo" : "photos"}.`, "success");
        exitSelect();
      }
      // saved === 0 => the user dismissed the save dialog; stay in select mode.
    } catch {
      toast("Couldn't download those photos.", "error");
    }
  }

  if (isInitialLoading) return <GridSkeleton />;
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
  if (total === 0) {
    return (
      <EmptyState
        icon={<Images className="size-8" aria-hidden="true" />}
        title="No photos yet"
        description="Upload photos to this event to see them here."
      />
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-end gap-3">
        {selectMode ? (
          <>
            <span className="mr-auto text-body-sm text-ink" role="status">
              {selected.size} selected
              {busy ? ` · downloading ${done} of ${dlTotal}` : ""}
            </span>
            <Button size="sm" onClick={downloadSelected} loading={busy} disabled={selected.size === 0}>
              Download {selected.size > 0 ? selected.size : ""}
            </Button>
            <Button size="sm" variant="ghost" onClick={exitSelect} disabled={busy}>
              Cancel
            </Button>
          </>
        ) : (
          <Button size="sm" variant="secondary" onClick={() => setSelectMode(true)}>
            Select
          </Button>
        )}
      </div>
      <PhotoGrid
        items={items.map((m) => ({
          id: m.id,
          mediaType: m.media_type,
          hasThumbnail: m.thumbnail_path !== null,
        }))}
        canManageAppearances
        onLoadMore={loadMore}
        hasMore={!reachedEnd}
        loadingMore={isLoadingMore}
        selectionMode={selectMode}
        selectedIds={selected}
        onToggleSelect={toggleSelect}
      />
    </div>
  );
}

function EventStudentPhotos({ eventId, studentId }: { eventId: string; studentId: string }) {
  const { media, isLoading, error } = useEventStudentMedia(eventId, studentId);

  if (isLoading) return <GridSkeleton />;
  if (error) return <p className="text-body-sm text-ink-secondary">Couldn&apos;t load photos.</p>;
  if (!media || media.length === 0) {
    return <p className="text-body-sm text-ink-secondary">No photos for this student.</p>;
  }
  return (
    <PhotoGrid
      items={media.map((m) => ({
        id: m.media_id,
        mediaType: m.media_type,
        hasThumbnail: m.has_thumbnail,
      }))}
      canManageAppearances
    />
  );
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
        description="Match this event's photos — students who appear in them show up here."
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

/** One ambiguous match awaiting a decision — a (photo, candidate-student) pair. */
type ReviewPair = {
  key: string;
  mediaId: string;
  mediaType: MediaType;
  studentId: string;
  name: string;
  confidence: number;
};

/** The batch review lane (BP13): every ambiguous match flattened to a per-student decision,
 *  sorted by confidence, with checkboxes → Confirm/Reject selected + a guarded "Reject all
 *  remaining". Each decision is exactly the single confirm/reject (BP5), applied to many. */
function NeedsReview({ eventId }: { eventId: string }) {
  const { reviews, isLoading, error, mutate } = useEventReview(eventId);
  const { toast } = useToast();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [rejectAllOpen, setRejectAllOpen] = useState(false);

  // Flatten photos → per-candidate pairs, highest confidence first (the obvious ones on top).
  const pairs = useMemo<ReviewPair[]>(() => {
    const out: ReviewPair[] = [];
    for (const r of reviews ?? []) {
      for (const c of r.candidates) {
        out.push({
          key: `${r.media_id}|${c.student_id}`,
          mediaId: r.media_id,
          mediaType: r.media_type,
          studentId: c.student_id,
          name: c.name,
          confidence: c.confidence,
        });
      }
    }
    out.sort((a, b) => b.confidence - a.confidence);
    return out;
  }, [reviews]);

  async function apply(keys: string[], verdict: "confirmed" | "rejected") {
    if (keys.length === 0) return;
    setBusy(true);
    try {
      const byKey = new Map(pairs.map((p) => [p.key, p]));
      const verdicts = keys
        .map((k) => byKey.get(k))
        .filter((p): p is ReviewPair => p !== undefined)
        .map((p) => ({ media_id: p.mediaId, student_id: p.studentId, verdict }));
      const { applied } = await batchReview(eventId, verdicts);
      toast(
        `${verdict === "confirmed" ? "Confirmed" : "Rejected"} ${applied} ${applied === 1 ? "match" : "matches"}.`,
        "success",
      );
      setSelected(new Set());
      await mutate();
      void globalMutate("dashboard"); // the "N to review" badge drops
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setBusy(false);
    }
  }

  if (isLoading) return <GridSkeleton />;
  if (error) {
    return (
      <EmptyState
        role="alert"
        title="Couldn't load review items"
        description="Something went wrong reaching the server."
        action={
          <Button variant="secondary" onClick={() => mutate()}>
            Retry
          </Button>
        }
      />
    );
  }
  if (pairs.length === 0) {
    return (
      <EmptyState
        title="Nothing to review"
        description="Ambiguous matches show up here to confirm or reject. You're all caught up."
      />
    );
  }

  const allSelected = selected.size === pairs.length;
  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(pairs.map((p) => p.key)));
  }
  function toggle(key: string) {
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-body-sm text-ink">
          <input
            type="checkbox"
            checked={allSelected}
            onChange={toggleAll}
            className="size-4 rounded border-hairline text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          Select all
          <span className="text-ink-muted">
            · {selected.size} of {pairs.length} selected · sorted by confidence
          </span>
        </label>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => apply([...selected], "confirmed")} loading={busy} disabled={selected.size === 0}>
            Confirm {selected.size > 0 ? selected.size : ""}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => apply([...selected], "rejected")}
            loading={busy}
            disabled={selected.size === 0}
          >
            Reject {selected.size > 0 ? selected.size : ""}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setRejectAllOpen(true)}
            disabled={busy}
          >
            Reject all remaining
          </Button>
        </div>
      </div>

      <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        {pairs.map((p) => {
          const isSel = selected.has(p.key);
          return (
            <li key={p.key}>
              <div
                className={cn(
                  "overflow-hidden rounded-card border transition-colors",
                  isSel ? "border-accent-hover ring-2 ring-ring" : "border-hairline",
                )}
              >
                <label className="relative block cursor-pointer">
                  <input
                    type="checkbox"
                    checked={isSel}
                    onChange={() => toggle(p.key)}
                    aria-label={`Select match for ${p.name}`}
                    className="absolute left-2 top-2 z-10 size-5 rounded border-hairline bg-canvas text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  />
                  <SignedImage
                    mediaId={p.mediaId}
                    kind={p.mediaType}
                    size="thumb"
                    alt=""
                    loading="square"
                    className="aspect-square w-full"
                    imgClassName="block w-full align-top"
                    fallbackText="Unavailable"
                  />
                </label>
                <div className="flex flex-col gap-1 p-3">
                  <div className="flex items-center gap-2">
                    {/* BP22: the candidate's reference face — decide by looking, not guessing. */}
                    <StudentRefAvatar studentId={p.studentId} name={p.name} className="size-7" />
                    <p className="min-w-0 flex-1 truncate text-body-sm text-ink" title={p.name}>
                      {p.name}
                    </p>
                    <span className="shrink-0 tabular-nums text-body-sm text-ink-muted">
                      {Math.round(p.confidence * 100)}%
                    </span>
                  </div>
                  <Link
                    href={`/photos/${p.mediaId}`}
                    className="rounded text-body-sm font-medium text-accent-hover hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    Open photo →
                  </Link>
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      <ConfirmDialog
        open={rejectAllOpen}
        onOpenChange={setRejectAllOpen}
        title="Reject all remaining?"
        description={`This rejects the remaining ${pairs.length} ${pairs.length === 1 ? "match" : "matches"} and hides those photos from the students in them. You can undo individual rejections later.`}
        confirmLabel="Reject all"
        loading={busy}
        onConfirm={() => apply(pairs.map((p) => p.key), "rejected")}
      />
    </div>
  );
}

const GALLERY_TABS = ["all", "by-student", "review"] as const;
type GalleryTab = (typeof GALLERY_TABS)[number];

export default function EventGalleryPage() {
  const { eventId } = useParams<{ eventId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { event } = useEvent(eventId);
  const { reviews } = useEventReview(eventId);
  // Count match PAIRS (sum of candidates), not photos — a photo can carry several ambiguous
  // candidates. Same unit + overlay the DistributionCard uses; the school-wide dashboard "N to
  // review" is a close approximation (raw minus resolved, clamped), not necessarily bit-exact.
  const reviewCount = (reviews ?? []).reduce((n, r) => n + r.candidates.length, 0);

  // BP22 (R3-A3-09): the active tab lives in the URL so a deep-link opens the right tab and
  // browser-back returns to it (the route is dynamic, so useSearchParams needs no Suspense).
  const tabParam = searchParams.get("tab");
  const tab: GalleryTab = GALLERY_TABS.includes(tabParam as GalleryTab)
    ? (tabParam as GalleryTab)
    : "all";
  function onTabChange(value: string) {
    router.replace(`/events/${eventId}/gallery?tab=${value}`, { scroll: false });
  }

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

      <Tabs value={tab} onValueChange={onTabChange}>
        <TabsList>
          <TabsTrigger value="all">All photos</TabsTrigger>
          <TabsTrigger value="by-student">By student</TabsTrigger>
          <TabsTrigger value="review">
            Needs review{reviewCount > 0 ? ` (${reviewCount})` : ""}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="all">
          <AllPhotos eventId={eventId} />
        </TabsContent>
        <TabsContent value="by-student">
          <ByStudent eventId={eventId} />
        </TabsContent>
        <TabsContent value="review">
          <NeedsReview eventId={eventId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
