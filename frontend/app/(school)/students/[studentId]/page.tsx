"use client";

import {
  AlertTriangle,
  Ban,
  CircleCheck,
  Download,
  ImagePlus,
  KeyRound,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { type FormEvent, useCallback, useMemo, useState } from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { FilterChips } from "@/components/gallery/filter-chips";
import { GridSkeleton } from "@/components/gallery/grid-skeleton";
import { PhotoGrid } from "@/components/gallery/photo-grid";
import { type Invite, InviteResultDialog } from "@/components/staff/invite-result-dialog";
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
  getStudentEngagement,
  resendStudentInvite,
  setStudentClass,
  setStudentReferencePhoto,
  setStudentStatus,
} from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type {
  EnrollmentFailureReason,
  EventForStudentResponse,
  StudentResponse,
  UserStatus,
} from "@/lib/api/types";
import { uploadReferencePhoto } from "@/lib/api/upload";
import { toISODate } from "@/lib/events/calendar";
import { useClasses } from "@/lib/hooks/use-classes";
import { useDownloadAll } from "@/lib/hooks/use-download-all";
import { useAllStudentMedia, useStudentEvents, useStudentMedia } from "@/lib/hooks/use-galleries";
import { useStudentReferencePhoto } from "@/lib/hooks/use-student-reference-photo";
import { useStudent } from "@/lib/hooks/use-students";
import { ENROLL_FAILURE_HELP, enrollDisplay } from "@/lib/students/enrollment";
import { formatDate, sanitizeFilename } from "@/lib/utils";

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
              <span aria-live="polite" className="text-body-sm text-ink-secondary">
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

/** One student's reach + engagement (BP23) — events/photos they appear in, how many they've
 *  opened + when, and their own downloads. Its own read (staff-only). Renders nothing on a
 *  load/error so it never blocks the profile. */
function EngagementCard({ studentId }: { studentId: string }) {
  const { data } = useSWR(`student-engagement:${studentId}`, () =>
    getStudentEngagement(studentId),
  );
  if (!data) return null;
  const stats: { label: string; value: string }[] = [
    { label: "Events they're in", value: data.events_appearing.toLocaleString() },
    { label: "Photos they're in", value: data.photos_appearing.toLocaleString() },
    { label: "Events opened", value: data.events_opened.toLocaleString() },
    {
      label: "Last opened",
      value: data.last_opened_at ? formatDate(data.last_opened_at) : "—",
    },
    { label: "Downloads", value: data.downloads.toLocaleString() },
  ];
  return (
    <Card className="flex flex-col gap-4 p-6">
      <h2 className="text-headline text-ink">Engagement</h2>
      <dl className="grid gap-6 sm:grid-cols-3">
        {stats.map((s) => (
          <div key={s.label} className="flex flex-col gap-1">
            <dt className="text-body-sm text-ink-secondary">{s.label}</dt>
            <dd className="text-body font-medium tabular-nums text-ink">{s.value}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

/** Staff "Download all": every photo this student appears in, across all their events, as ONE
 *  zip — foldered/named by event/date. The staff-side of the student's own "Download all" (BP26 v1,
 *  decisions/0081 — the v1 distribution model: staff download → share via WhatsApp). Reuses the
 *  download entitlement (both staff roles hold `gallery:view_all`) + the streaming `useDownloadAll`
 *  — no backend change. `events` is the already-fetched list (for zip foldering); the full media list
 *  is its own read, and its count is the EFFECTIVE set (BP5 corrections applied) — so it can differ
 *  from the EngagementCard's raw `photos_appearing`. */
function StudentDownloadAll({
  studentId,
  studentName,
  events,
}: {
  studentId: string;
  studentName: string;
  events: EventForStudentResponse[];
}) {
  const { toast } = useToast();
  const { media, error } = useAllStudentMedia(studentId);

  // event_id → {name, date} for zip foldering (mirrors the student self-view, BP20).
  const eventMeta = useMemo(() => {
    const m = new Map<string, { name: string; date: string | null }>();
    for (const e of events) m.set(e.event_id, { name: e.name, date: e.event_date });
    return m;
  }, [events]);

  const mediaIds = useMemo(() => (media ? media.map((x) => x.media_id) : []), [media]);
  // `new Date()` in a lazy initializer runs once at mount, not on every render.
  const [zipStamp] = useState(() => toISODate(new Date()));
  const entryBase = useCallback(
    (i: number) => {
      const m = media?.[i];
      const meta = m ? eventMeta.get(m.event_id) : undefined;
      const folder = (meta && sanitizeFilename(meta.name)) || "Photos";
      const datePart = meta?.date ?? "photo";
      return `${folder}/${datePart}-${String(i + 1).padStart(3, "0")}`;
    },
    [media, eventMeta],
  );
  const zipName = `${sanitizeFilename(studentName) || "student"}-photos-${zipStamp}.zip`;
  const { busy, done, total, cap, onDownloadAll } = useDownloadAll(mediaIds, {
    entryBase,
    zipName,
  });

  async function handleDownloadAll() {
    try {
      const { saved, capped, cancelled } = await onDownloadAll();
      if (cancelled) return; // dismissed the save dialog — silent, not an error
      // Copy mirrors the sibling staff surface (the event-gallery download) for consistency.
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

  // The list read failed, or the student has no photos → no button (the per-event view still
  // works). While the list loads, the button shows disabled with no count.
  if (error) return null;
  if (media && media.length === 0) return null;
  return (
    <div className="flex items-center gap-3">
      <Button
        variant="secondary"
        onClick={handleDownloadAll}
        loading={busy}
        disabled={busy || !media}
      >
        <Download className="size-4" aria-hidden="true" />
        {busy
          ? `Preparing ${done}/${total}…`
          : media
            ? `Download all ${total} ${total === 1 ? "photo" : "photos"}`
            : "Download all photos"}
      </Button>
      {/* SR-only progress (mirrors the student self-view): a *visible* per-tick live region would
          announce on every photo; the button-label flip covers sighted users. */}
      {busy ? (
        <span className="sr-only" aria-live="polite">
          Preparing {done} of {total} photos
        </span>
      ) : null}
    </div>
  );
}

/** Events the student appears in → their photos in the selected one, plus a staff "Download all"
 *  (BP26 v1). Hidden until the student has been matched into at least one photo (decisions/0035). */
function AppearsInSection({ studentId, studentName }: { studentId: string; studentName: string }) {
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
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-headline text-ink">Appears in</h2>
        <StudentDownloadAll studentId={studentId} studentName={studentName} events={events} />
      </div>
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
  const [sending, setSending] = useState(false);
  const [statusSaving, setStatusSaving] = useState(false);
  const [disableConfirmOpen, setDisableConfirmOpen] = useState(false);
  const [invite, setInvite] = useState<Invite | null>(null);

  const notFound = isApiError(error) && error.status === 404;

  async function onReenroll() {
    setReenrolling(true);
    try {
      const updated = await enrollStudent(studentId);
      await mutate(updated, { revalidate: false });
      void globalMutate("students"); // keep the list's enrollment pill in sync
      toast(
        updated.enrollment_status === "enrolled"
          ? "Re-enrolled."
          : "Enrollment didn't succeed — check the reason below.",
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

  async function onResend() {
    setSending(true);
    try {
      // BP18a: recovery WITHOUT the destructive delete — regenerates the temp password,
      // shown once. The student's photos + matches are untouched.
      const { student: s, temp_password } = await resendStudentInvite(studentId);
      setInvite({ email: s.email, tempPassword: temp_password });
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setSending(false);
    }
  }

  async function onToggleStatus(next: UserStatus) {
    setStatusSaving(true);
    try {
      // BP18d: a non-destructive kill-switch — a disabled student can't sign in but keeps
      // every photo + match row (unlike delete). Reversible: re-enable restores access.
      const updated = await setStudentStatus(studentId, next);
      await mutate(updated, { revalidate: false });
      void globalMutate("students"); // keep the list in sync
      toast(next === "disabled" ? "Login disabled." : "Login enabled.", "success");
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setStatusSaving(false);
      setDisableConfirmOpen(false);
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
                    disabled={deleting || sending}
                  >
                    <RefreshCw className="size-4" aria-hidden="true" />
                    Re-enroll
                  </Button>
                ) : null}
                {/* BP18a: give a locked-out student a fresh password without deleting them
                    (delete would erase their photo history). */}
                <Button
                  variant="secondary"
                  onClick={onResend}
                  loading={sending}
                  disabled={reenrolling || deleting || statusSaving}
                >
                  <KeyRound className="size-4" aria-hidden="true" />
                  Send new password
                </Button>
                {/* BP18d: a non-destructive kill-switch — disable a student's login without
                    deleting them (delete erases their photo history). Enabling is direct;
                    disabling asks first (it locks the student out until re-enabled). */}
                {student.status === "disabled" ? (
                  <Button
                    variant="secondary"
                    onClick={() => onToggleStatus("active")}
                    loading={statusSaving}
                    disabled={reenrolling || sending || deleting}
                  >
                    <CircleCheck className="size-4" aria-hidden="true" />
                    Enable login
                  </Button>
                ) : (
                  <Button
                    variant="secondary"
                    onClick={() => setDisableConfirmOpen(true)}
                    disabled={reenrolling || sending || deleting || statusSaving}
                  >
                    <Ban className="size-4" aria-hidden="true" />
                    Disable login
                  </Button>
                )}
                <Button
                  variant="destructive"
                  onClick={() => setConfirmOpen(true)}
                  disabled={reenrolling || sending || statusSaving}
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
                  <dt className="text-body-sm text-ink-secondary">Enrollment</dt>
                  <dd>
                    <StatusPill tone={enrollDisplay(student).tone}>
                      {enrollDisplay(student).label}
                    </StatusPill>
                  </dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-secondary">Login</dt>
                  <dd>
                    <StatusPill tone={student.status === "disabled" ? "neutral" : "success"}>
                      {student.status === "disabled" ? "Disabled" : "Active"}
                    </StatusPill>
                  </dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-secondary">Added</dt>
                  <dd className="text-body text-ink">{formatDate(student.created_at)}</dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-secondary">Class</dt>
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
          <EngagementCard studentId={studentId} />
          <AppearsInSection studentId={studentId} studentName={student.name} />
        </>
      )}

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Delete student?"
        description="Permanently deletes their login, profile, face enrollment, and their matched-photo history (which photos they appear in) — this can't be undone. The event photos themselves stay in every gallery, and past download records are kept but anonymized."
        confirmLabel="Delete student"
        destructive
        loading={deleting}
        onConfirm={onDelete}
      />

      <ConfirmDialog
        open={disableConfirmOpen}
        onOpenChange={setDisableConfirmOpen}
        title="Disable this student's login?"
        description="They won't be able to sign in until you re-enable it. Their photos and history are kept — nothing is deleted."
        confirmLabel="Disable login"
        loading={statusSaving}
        onConfirm={() => onToggleStatus("disabled")}
      />

      <InviteResultDialog invite={invite} onClose={() => setInvite(null)} />
    </div>
  );
}
