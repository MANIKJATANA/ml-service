"use client";

import { GraduationCap, RotateCcw, UserPlus } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useState } from "react";

import { StudentAvatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { FileDropzone } from "@/components/ui/file-dropzone";
import { FocusToggle } from "@/components/delegation/focus-toggle";
import { type ChipItem, FilterChips } from "@/components/gallery/filter-chips";
import { type Invite, InviteResultDialog } from "@/components/staff/invite-result-dialog";
import { BulkImportDialog } from "@/components/students/bulk-import-dialog";
import { BulkPhotoDialog } from "@/components/students/bulk-photo-dialog";
import { Input } from "@/components/ui/input";
import { LoadMore } from "@/components/ui/load-more";
import { PageHeader } from "@/components/ui/page-header";
import { ProgressBar } from "@/components/ui/progress-bar";
import { SearchInput } from "@/components/ui/search-input";
import { Skeleton } from "@/components/ui/skeleton";
import { SortableHead } from "@/components/ui/sortable-head";
import { StatusPill } from "@/components/ui/status-pill";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { createStudent, enrollStudent, getStudents } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import { uploadReferencePhoto } from "@/lib/api/upload";
import type { EnrollmentStatus, SortDir, StudentListItem } from "@/lib/api/types";
import { useClasses } from "@/lib/hooks/use-classes";
import { useDashboard } from "@/lib/hooks/use-dashboard";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { useMe } from "@/lib/hooks/use-me";
import { useMyClasses } from "@/lib/hooks/use-my-classes";
import { useListSort } from "@/lib/hooks/use-sort";
import { useStudentReferencePhoto } from "@/lib/hooks/use-student-reference-photo";
import { useStudents } from "@/lib/hooks/use-students";
import {
  ENROLL_FAILURE_SHORT,
  ENROLL_LABEL,
  ENROLL_TONE,
} from "@/lib/students/enrollment";

// The default sort direction when a column is first selected (BP9): names A→Z, counts
// most-first. Clicking an already-active column toggles the direction.
const SORT_DEFAULT_DIR: Record<string, SortDir> = {
  name: "asc",
  appearance_count: "desc",
};

function CreateStudentDialog({
  onCreated,
  onInvited,
}: {
  onCreated: () => void;
  onInvited: (invite: Invite) => void;
}) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploadedPath, setUploadedPath] = useState<string | null>(null); // survives a failed create
  const [progress, setProgress] = useState<number | null>(null); // non-null while uploading
  const [submitting, setSubmitting] = useState(false);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      setName("");
      setEmail("");
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
      // Upload the photo straight to Supabase, then create the student with its path (the
      // backend generates the BP17 thumbnail). Memoize the uploaded path so fixing a rejected
      // field (e.g. a duplicate email) and resubmitting doesn't re-upload the same photo.
      let objectPath = uploadedPath;
      if (!objectPath) {
        setProgress(0);
        objectPath = await uploadReferencePhoto(file, setProgress);
        setProgress(null);
        setUploadedPath(objectPath);
      }
      // BP7d: the temp password is server-generated + returned once.
      const { student, temp_password } = await createStudent(
        name.trim(),
        email.trim(),
        objectPath,
      );
      toast("Student created.", "success");
      onCreated();
      handleOpenChange(false);
      onInvited({ email: student.email, tempPassword: temp_password });
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
        <Button>
          <UserPlus className="size-4" aria-hidden="true" />
          Add student
        </Button>
      </DialogTrigger>
      <DialogContent
        title="Add student"
        description="Creates a student login (with a temporary password shown once) and enrolls their face from the reference photo."
      >
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <Field label="Full name" htmlFor="student-name">
            <Input
              id="student-name"
              required
              autoFocus
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label="Email" htmlFor="student-email">
            <Input
              id="student-email"
              type="email"
              autoComplete="off"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
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
              Add student
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** The student-list avatar (BP17): lazily fetches the reference photo, gated on a non-null
 *  path so photoless rows skip the fetch (no N pointless 404s); falls back to initials while
 *  loading / on error / when photoless. Requests the small thumbnail only when one exists,
 *  else the full-res photo (a pre-BP17 / generation-failed student still shows its face). */
function StudentRowAvatar({ student }: { student: StudentListItem }) {
  const { photoUrl } = useStudentReferencePhoto(
    student.id,
    student.reference_photo_path !== null,
    student.reference_photo_thumbnail_path !== null ? "thumb" : "full",
  );
  return <StudentAvatar name={student.name} photoUrl={photoUrl} />;
}

/** Collect the ids of all `failed` students, paging the list (bounded) — the source for the
 *  one-click bulk re-enroll (BP10, decisions/0057). */
async function collectFailedStudentIds(): Promise<string[]> {
  const ids: string[] = [];
  const LIMIT = 100;
  const CAP = 1000; // bound the retry batch
  let offset = 0;
  for (;;) {
    const page = await getStudents({ limit: LIMIT, offset, status: "failed" });
    ids.push(...page.items.map((s) => s.id));
    offset += LIMIT;
    if (page.items.length < LIMIT || offset >= page.total || ids.length >= CAP) break;
  }
  return ids.slice(0, CAP);
}

/** "Retry failed (N)": re-run ML enrollment for every `failed` student (they already have a
 *  photo — a transient blip like ML-down is fixed on retry) through a small pool. BP10. */
function RetryFailedButton({
  failedCount,
  onDone,
}: {
  failedCount: number;
  onDone: () => void;
}) {
  const { toast } = useToast();
  const [confirming, setConfirming] = useState(false);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);

  async function run() {
    setConfirming(false);
    setRunning(true);
    try {
      const ids = await collectFailedStudentIds();
      if (ids.length === 0) {
        // The failures cleared between the dashboard rollup and the click — refresh so the
        // stale "Retry failed (N)" count that made this button appear corrects itself.
        toast("No failed enrollments to retry.", "info");
        onDone();
        return;
      }
      setProgress({ done: 0, total: ids.length });
      let ok = 0;
      let done = 0;
      let idx = 0;
      const CONCURRENCY = 3;
      const worker = async () => {
        while (idx < ids.length) {
          const id = ids[idx++];
          try {
            const s = await enrollStudent(id);
            if (s.enrollment_status === "enrolled") ok += 1;
          } catch {
            // Isolated — one failure (e.g. ML still down) never aborts the batch.
          }
          done += 1;
          setProgress({ done, total: ids.length });
        }
      };
      await Promise.all(Array.from({ length: Math.min(CONCURRENCY, ids.length) }, worker));
      toast(
        ok > 0
          ? `Re-enrolled ${ok} of ${ids.length} student${ids.length === 1 ? "" : "s"}.`
          : "No enrollments succeeded — replace the photos or try again once ML is back.",
        ok > 0 ? "success" : "info",
      );
      onDone();
    } catch (err) {
      toast(isApiError(err) ? err.message : "Retry failed. Please try again.", "error");
    } finally {
      setRunning(false);
      setProgress(null);
    }
  }

  return (
    <>
      <Button variant="secondary" onClick={() => setConfirming(true)} disabled={running}>
        <RotateCcw className="size-4" aria-hidden="true" />
        {progress
          ? `Retrying ${progress.done}/${progress.total}…`
          : `Retry failed (${failedCount})`}
      </Button>
      {/* The button is disabled while running (its label change isn't reliably announced), so
          announce the start once here; the toast announces the final result. */}
      <span role="status" aria-live="polite" className="sr-only">
        {progress ? `Retrying ${progress.total} enrollments…` : ""}
      </span>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Retry failed enrollments?"
        description={`Re-run ML enrollment for ${failedCount} student${failedCount === 1 ? "" : "s"} using their existing photos. A photo with no clear face won't change on retry — replace it instead.`}
        confirmLabel="Retry"
        onConfirm={run}
      />
    </>
  );
}

export default function StudentsPage() {
  const [rawQuery, setRawQuery] = useState("");
  const query = useDebouncedValue(rawQuery.trim(), 300);
  const [filter, setFilter] = useState<"all" | EnrollmentStatus>("all");
  const [classFilter, setClassFilter] = useState(""); // "" = all classes (BP11a)
  const [focus, setFocus] = useState(true); // BP11c: default a teacher to their classes
  const { sort, dir, onSort } = useListSort("name", SORT_DEFAULT_DIR);
  const [invite, setInvite] = useState<Invite | null>(null);

  const { dashboard, mutate: mutateDashboard } = useDashboard();
  const { classes } = useClasses();
  const { user } = useMe();
  const isTeacher = user?.role === "teacher";
  const { classes: myClasses } = useMyClasses(isTeacher);
  // BP11c: the focus toggle is only meaningful for a teacher who actually has classes.
  const canFocus = isTeacher && myClasses.length > 0;
  const focusOn = canFocus && focus;
  // BP11a: if the selected class was deleted (or every class was), fall back to "all" — derived
  // (not reconciled via an effect) so the list never gets stuck filtering a class that's gone.
  const activeClassFilter =
    classFilter && classes.some((c) => c.id === classFilter) ? classFilter : "";
  const { items, total, isLoading, isLoadingMore, error, reachedEnd, loadMore, mutate } =
    useStudents({
      q: query || undefined,
      sort,
      dir,
      status: filter,
      student_group_id: activeClassFilter || undefined,
      mine: focusOn,
    });

  const counts = dashboard?.students;
  const chips: ChipItem[] = [
    { id: "all", label: "All", count: counts?.total },
    { id: "enrolled", label: "Enrolled", count: counts?.enrolled },
    { id: "pending", label: "Pending", count: counts?.pending },
    { id: "failed", label: "Failed", count: counts?.failed },
  ];

  const isInitialLoading = isLoading && items.length === 0;
  const isFiltering =
    filter !== "all" || query.length > 0 || activeClassFilter !== "" || focusOn;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Students"
        description="Enroll students so they receive the photos they appear in."
        actions={
          <div className="flex flex-wrap gap-2">
            {(counts?.failed ?? 0) > 0 ? (
              <RetryFailedButton
                failedCount={counts?.failed ?? 0}
                onDone={() => {
                  mutate();
                  void mutateDashboard();
                }}
              />
            ) : null}
            <BulkImportDialog onImported={() => mutate()} />
            <BulkPhotoDialog
              onDone={() => {
                mutate();
                void mutateDashboard();
              }}
            />
            <CreateStudentDialog onCreated={() => mutate()} onInvited={setInvite} />
          </div>
        }
      />

      {isInitialLoading ? (
        <Card className="flex flex-col gap-2 p-4">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </Card>
      ) : error ? (
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
      ) : total === 0 && !isFiltering ? (
        <EmptyState
          icon={<GraduationCap className="size-8" aria-hidden="true" />}
          title="No students yet"
          description="Add a student and upload their reference photo, or import a whole class from CSV."
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <CreateStudentDialog onCreated={() => mutate()} onInvited={setInvite} />
              <BulkImportDialog onImported={() => mutate()} />
            </div>
          }
        />
      ) : (
        <div className="flex flex-col gap-4">
          {/* Row 1: the primary status filter on its own line so it isn't crowded. */}
          <FilterChips
            items={chips}
            activeId={filter}
            onSelect={(id) => setFilter(id as "all" | EnrollmentStatus)}
            ariaLabel="Filter by enrollment status"
          />
          {/* Row 2: the scope toggle + class filter (left) and search (right). */}
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              {canFocus ? <FocusToggle value={focus} onChange={setFocus} /> : null}
              {classes.length > 0 ? (
                <select
                  aria-label="Filter by class"
                  value={activeClassFilter}
                  onChange={(e) => setClassFilter(e.target.value)}
                  className="h-10 rounded-button border border-hairline bg-canvas px-3 text-body text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <option value="">All classes</option>
                  {classes.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              ) : null}
            </div>
            <SearchInput value={rawQuery} onChange={setRawQuery} placeholder="Search name or email…" />
          </div>
          {total === 0 ? (
            <EmptyState title="No matching students" description="Try a different search or filter." />
          ) : (
            <>
              <Card className="overflow-hidden">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <SortableHead
                        label="Student"
                        sortKey="name"
                        activeKey={sort}
                        dir={dir}
                        onSort={onSort}
                      />
                      <TableHead>Email</TableHead>
                      <SortableHead
                        label="Appears in"
                        sortKey="appearance_count"
                        activeKey={sort}
                        dir={dir}
                        onSort={onSort}
                      />
                      <TableHead>Enrollment</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((student) => (
                      <TableRow key={student.id} className="transition-colors hover:bg-surface">
                        <TableCell>
                          <Link
                            href={`/students/${student.id}`}
                            className="flex items-center gap-3 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          >
                            <StudentRowAvatar student={student} />
                            <span className="flex flex-col">
                              <span className="font-medium text-ink hover:underline">
                                {student.name}
                              </span>
                              {student.student_group_name ? (
                                <span className="text-body-sm text-ink-muted">
                                  {student.student_group_name}
                                </span>
                              ) : null}
                            </span>
                          </Link>
                        </TableCell>
                        <TableCell className="text-ink-secondary">{student.email}</TableCell>
                        <TableCell className="text-ink-secondary">
                          {student.appearance_count > 0 ? (
                            <span className="tabular-nums">
                              {student.appearance_count} photo
                              {student.appearance_count === 1 ? "" : "s"} · {student.event_count} event
                              {student.event_count === 1 ? "" : "s"}
                            </span>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-col items-start gap-0.5">
                            <StatusPill tone={ENROLL_TONE[student.enrollment_status]}>
                              {ENROLL_LABEL[student.enrollment_status]}
                            </StatusPill>
                            {student.enrollment_status === "failed" &&
                            student.enrollment_failure_reason ? (
                              <span className="text-body-sm text-ink-secondary">
                                {ENROLL_FAILURE_SHORT[student.enrollment_failure_reason]}
                              </span>
                            ) : null}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Card>
              <LoadMore
                shown={items.length}
                total={total}
                reachedEnd={reachedEnd}
                loading={isLoadingMore}
                onLoadMore={loadMore}
              />
            </>
          )}
        </div>
      )}

      <InviteResultDialog invite={invite} onClose={() => setInvite(null)} />
    </div>
  );
}
