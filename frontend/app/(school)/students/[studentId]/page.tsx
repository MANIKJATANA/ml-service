"use client";

import { AlertTriangle, ImagePlus, RefreshCw, Trash2 } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { mutate as globalMutate } from "swr";

import { FilterChips } from "@/components/gallery/filter-chips";
import { GridSkeleton } from "@/components/gallery/grid-skeleton";
import { PhotoGrid } from "@/components/gallery/photo-grid";
import { StudentAvatar } from "@/components/ui/avatar";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { FileDropzone } from "@/components/ui/file-dropzone";
import { PageHeader } from "@/components/ui/page-header";
import { ProgressBar } from "@/components/ui/progress-bar";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { useToast } from "@/components/ui/toast";
import {
  deleteStudent,
  enrollStudent,
  setStudentClass,
  setStudentReferencePhoto,
} from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { EnrollmentFailureReason, StudentResponse } from "@/lib/api/types";
import { uploadReferencePhoto } from "@/lib/api/upload";
import { useClasses } from "@/lib/hooks/use-classes";
import { useStudentEvents, useStudentMedia } from "@/lib/hooks/use-galleries";
import { useStudentReferencePhoto } from "@/lib/hooks/use-student-reference-photo";
import { useStudent } from "@/lib/hooks/use-students";
import { ENROLL_FAILURE_HELP, ENROLL_LABEL, ENROLL_TONE } from "@/lib/students/enrollment";
import { formatDate } from "@/lib/utils";

/** Why an enrollment failed + how to fix it (BP7b). Shown under the profile when the
 *  status is `failed`; the specific copy comes from the reason the backend recorded. */
function EnrollmentFailureNote({ reason }: { reason: EnrollmentFailureReason | null }) {
  const help = reason ? ENROLL_FAILURE_HELP[reason] : null;
  return (
    <Card role="alert" className="flex items-start gap-3 border-error/30 bg-error/5 p-4">
      <AlertTriangle className="mt-0.5 size-5 shrink-0 text-error" aria-hidden="true" />
      <div className="flex flex-col gap-1">
        <p className="text-body-sm font-medium text-ink">
          {help ? help.title : "Enrollment failed"}
        </p>
        <p className="text-body-sm text-ink-secondary">
          {help ? help.fix : "Replace the reference photo with a clearer one."}
        </p>
      </div>
    </Card>
  );
}

/** Add (photoless student) or replace (fix a bad photo) a reference photo, then re-enroll
 *  (BP7d-2). Uploads straight to Supabase, then PUTs the object path; the caller refreshes
 *  from the returned, freshly-enrolled student. */
function ReferencePhotoDialog({
  studentId,
  hasPhoto,
  onUpdated,
}: {
  studentId: string;
  hasPhoto: boolean;
  onUpdated: (student: StudentResponse) => void;
}) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [uploadedPath, setUploadedPath] = useState<string | null>(null); // survives a failed PUT
  const [progress, setProgress] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const label = hasPhoto ? "Replace photo" : "Add photo";

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      setFile(null);
      setUploadedPath(null);
      setProgress(null);
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      toast("Please choose a reference photo.", "error");
      return;
    }
    setSubmitting(true);
    try {
      // Upload the photo, then set it (the backend generates the BP17 thumbnail + re-enrolls).
      // Memoize the path so a failed backend PUT doesn't re-upload on retry.
      let objectPath = uploadedPath;
      if (!objectPath) {
        setProgress(0);
        objectPath = await uploadReferencePhoto(file, setProgress);
        setProgress(null);
        setUploadedPath(objectPath);
      }
      const updated = await setStudentReferencePhoto(studentId, objectPath);
      handleOpenChange(false);
      onUpdated(updated);
      toast(
        updated.enrollment_status === "enrolled"
          ? "Photo saved and enrolled."
          : "Photo saved, but enrollment didn't succeed — check the reason.",
        updated.enrollment_status === "enrolled" ? "success" : "warning",
      );
    } catch (err) {
      setProgress(null);
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="secondary" disabled={submitting}>
          <ImagePlus className="size-4" aria-hidden="true" />
          {label}
        </Button>
      </DialogTrigger>
      <DialogContent
        title={label}
        description="Uploads the photo and enrolls the student's face. A clear, front-facing photo works best."
      >
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <FileDropzone
            file={file}
            onFileChange={(next) => {
              setFile(next);
              setUploadedPath(null); // a new file must be re-uploaded
            }}
            disabled={submitting}
            hint="An image up to 30 MB."
          />
          {progress !== null ? (
            <div className="flex flex-col gap-1.5">
              <ProgressBar value={progress} label="Upload progress" />
              <span aria-live="polite" className="text-body-sm text-ink-muted">
                Uploading photo… {progress}%
              </span>
            </div>
          ) : null}
          <div className="mt-2 flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="secondary">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" loading={submitting}>
              {label}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Assign/change/clear the student's class (BP11a). A compact inline select in the profile;
 *  writes through `setStudentClass` and refreshes the student + the class-count caches. */
function ClassSelect({
  studentId,
  current,
  onChanged,
}: {
  studentId: string;
  current: string | null;
  onChanged: (student: StudentResponse) => void;
}) {
  const { toast } = useToast();
  const { classes } = useClasses();
  const [saving, setSaving] = useState(false);

  async function onChange(value: string) {
    setSaving(true);
    try {
      const updated = await setStudentClass(studentId, value || null);
      onChanged(updated);
      void globalMutate("students"); // the list shows a class badge
      void globalMutate("classes"); // and the classes list shows member counts
      toast(value ? "Class updated." : "Removed from class.", "success");
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <select
      aria-label="Class"
      value={current ?? ""}
      disabled={saving}
      onChange={(e) => onChange(e.target.value)}
      className="h-9 rounded-button border border-hairline bg-canvas px-2.5 text-body-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
    >
      <option value="">No class</option>
      {classes.map((c) => (
        <option key={c.id} value={c.id}>
          {c.name}
        </option>
      ))}
    </select>
  );
}

function StudentEventPhotos({ studentId, eventId }: { studentId: string; eventId: string }) {
  const { media, isLoading, error } = useStudentMedia(studentId, eventId);
  if (isLoading) return <GridSkeleton />;
  if (error) return <p className="text-body-sm text-ink-secondary">Couldn&apos;t load photos.</p>;
  if (!media || media.length === 0) {
    return <p className="text-body-sm text-ink-secondary">No photos in this event.</p>;
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
  // BP17: the header avatar's reference-photo thumbnail (full size for the larger avatar),
  // gated on a non-null path so a photoless student skips the fetch. Falls back to initials.
  const { photoUrl } = useStudentReferencePhoto(
    studentId,
    student?.reference_photo_path != null,
    "full",
  );

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

  async function onPhotoUpdated(updated: StudentResponse) {
    await mutate(updated, { revalidate: false });
    void globalMutate("students"); // keep the list's enrollment pill in sync
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
                <ReferencePhotoDialog
                  studentId={studentId}
                  hasPhoto={student.reference_photo_path !== null}
                  onUpdated={onPhotoUpdated}
                />
                {/* Re-enroll retries the STORED photo — hidden for a photoless student
                    (they'd 400); use "Add photo" instead. */}
                {student.reference_photo_path !== null ? (
                  <Button
                    variant="secondary"
                    onClick={onReenroll}
                    loading={reenrolling}
                    disabled={deleting}
                  >
                    <RefreshCw className="size-4" aria-hidden="true" />
                    Re-enroll
                  </Button>
                ) : null}
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
                <StudentAvatar
                  name={student.name}
                  photoUrl={photoUrl}
                  className="size-12 text-body"
                />
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
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-muted">Class</dt>
                  <dd>
                    <ClassSelect
                      studentId={studentId}
                      current={student.student_group_id}
                      onChanged={(updated) => {
                        void mutate(updated, { revalidate: false });
                      }}
                    />
                  </dd>
                </div>
              </dl>
            </div>
          </Card>
          {student.enrollment_status === "failed" ? (
            <EnrollmentFailureNote reason={student.enrollment_failure_reason} />
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
