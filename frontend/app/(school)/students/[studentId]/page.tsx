"use client";

import { RefreshCw, Trash2 } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { mutate as globalMutate } from "swr";

import { FilterChips } from "@/components/gallery/filter-chips";
import { GridSkeleton } from "@/components/gallery/grid-skeleton";
import { PhotoGrid } from "@/components/gallery/photo-grid";
import { StudentAvatar } from "@/components/ui/avatar";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { useToast } from "@/components/ui/toast";
import { deleteStudent, enrollStudent } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import { useStudentEvents, useStudentMedia } from "@/lib/hooks/use-galleries";
import { useStudent } from "@/lib/hooks/use-students";
import { ENROLL_LABEL, ENROLL_TONE } from "@/lib/students/enrollment";
import { formatDate } from "@/lib/utils";

function StudentEventPhotos({ studentId, eventId }: { studentId: string; eventId: string }) {
  const { media, isLoading, error } = useStudentMedia(studentId, eventId);
  if (isLoading) return <GridSkeleton />;
  if (error) return <p className="text-body-sm text-ink-secondary">Couldn&apos;t load photos.</p>;
  if (!media || media.length === 0) {
    return <p className="text-body-sm text-ink-secondary">No photos in this event.</p>;
  }
  return <PhotoGrid mediaIds={media.map((m) => m.media_id)} canManageAppearances />;
}

/** Events the student appears in → their photos in the selected one. Hidden until the
 *  student has been matched into at least one photo (decisions/0035). */
function AppearsInSection({ studentId }: { studentId: string }) {
  const { events, isLoading, error } = useStudentEvents(studentId);
  const [picked, setPicked] = useState<string | null>(null);

  if (isLoading) {
    return (
      <Card className="flex flex-col gap-4 p-6">
        <Skeleton className="h-5 w-32" />
        <GridSkeleton />
      </Card>
    );
  }
  if (error || !events || events.length === 0) return null;

  const activeId = picked ?? events[0].event_id;
  return (
    <Card className="flex flex-col gap-4 p-6">
      <h2 className="text-headline text-ink">Appears in</h2>
      <FilterChips
        ariaLabel="Events"
        items={events.map((e) => ({ id: e.event_id, label: e.name, count: e.media_count }))}
        activeId={activeId}
        onSelect={setPicked}
      />
      <StudentEventPhotos studentId={studentId} eventId={activeId} />
    </Card>
  );
}

export default function StudentDetailPage() {
  const { studentId } = useParams<{ studentId: string }>();
  const router = useRouter();
  const { toast } = useToast();
  const { student, isLoading, error, mutate } = useStudent(studentId);

  const [reenrolling, setReenrolling] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const notFound = isApiError(error) && error.status === 404;

  async function onReenroll() {
    setReenrolling(true);
    try {
      const updated = await enrollStudent(studentId);
      await mutate(updated, { revalidate: false });
      void globalMutate("students"); // keep the list's enrollment pill in sync
      toast(
        updated.enrollment_status === "enrolled" ? "Re-enrolled." : "Enrollment still failed.",
        updated.enrollment_status === "enrolled" ? "success" : "warning",
      );
    } catch (err) {
      // ML-down isn't a throw here — enroll returns 200 with status "failed" (the warning
      // branch above). This only fires on 404 / expired-session / network failures.
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setReenrolling(false);
    }
  }

  async function onDelete() {
    setDeleting(true);
    try {
      await deleteStudent(studentId);
      void globalMutate("students"); // drop the deleted row from the list cache
      void globalMutate(`students/${studentId}`, undefined, { revalidate: false }); // and its stale detail entry
      toast("Student deleted.", "success");
      router.push("/students");
      router.refresh();
    } catch (err) {
      // 502 = ML delete failed (embeddings must be removed first) — operator retries.
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
      setDeleting(false);
      setConfirmOpen(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Breadcrumb
        items={[{ label: "Students", href: "/students" }, { label: student?.name ?? "Student" }]}
      />

      {isLoading ? (
        <>
          <Skeleton className="h-9 w-64" />
          <Card className="flex flex-col gap-3 p-6">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-4 w-32" />
          </Card>
        </>
      ) : error || !student ? (
        <EmptyState
          role="alert"
          title={notFound ? "Student not found" : "Couldn't load student"}
          description={
            notFound ? "It may have been removed." : "Something went wrong reaching the server."
          }
          action={
            notFound ? undefined : (
              <Button variant="secondary" onClick={() => mutate()}>
                Retry
              </Button>
            )
          }
        />
      ) : (
        <>
          <PageHeader
            title={student.name}
            actions={
              <>
                <Button
                  variant="secondary"
                  onClick={onReenroll}
                  loading={reenrolling}
                  disabled={deleting}
                >
                  <RefreshCw className="size-4" aria-hidden="true" />
                  Re-enroll
                </Button>
                <Button
                  variant="destructive"
                  onClick={() => setConfirmOpen(true)}
                  disabled={reenrolling}
                >
                  <Trash2 className="size-4" aria-hidden="true" />
                  Delete
                </Button>
              </>
            }
          />
          <Card className="p-6">
            <div className="flex flex-col gap-6">
              <div className="flex items-center gap-4">
                <StudentAvatar name={student.name} className="size-12 text-body" />
                <div className="flex flex-col gap-0.5">
                  <span className="text-headline text-ink">{student.name}</span>
                  <span className="text-body-sm text-ink-secondary">{student.email}</span>
                </div>
              </div>
              <dl className="grid gap-6 sm:grid-cols-2">
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-muted">Enrollment</dt>
                  <dd>
                    <StatusPill tone={ENROLL_TONE[student.enrollment_status]}>
                      {ENROLL_LABEL[student.enrollment_status]}
                    </StatusPill>
                  </dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-muted">Added</dt>
                  <dd className="text-body text-ink">{formatDate(student.created_at)}</dd>
                </div>
              </dl>
            </div>
          </Card>
          {student.enrollment_status === "failed" ? (
            <p className="text-body-sm text-ink-secondary">
              Enrollment failed — the reference photo may have no clear face, or the ML service was
              unavailable. Try Re-enroll, or delete and re-add with a clearer photo.
            </p>
          ) : null}
          <AppearsInSection studentId={studentId} />
        </>
      )}

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Delete student?"
        description="This removes the student's login, profile, and face enrollment. This can't be undone."
        confirmLabel="Delete student"
        destructive
        loading={deleting}
        onConfirm={onDelete}
      />
    </div>
  );
}
