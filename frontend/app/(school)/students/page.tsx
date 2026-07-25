"use client";

import { GraduationCap, UserPlus } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useState } from "react";

import { StudentAvatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { FileDropzone } from "@/components/ui/file-dropzone";
import { type ChipItem, FilterChips } from "@/components/gallery/filter-chips";
import { type Invite, InviteResultDialog } from "@/components/staff/invite-result-dialog";
import { BulkImportDialog } from "@/components/students/bulk-import-dialog";
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
import { createStudent } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import { uploadReferencePhoto } from "@/lib/api/upload";
import type { EnrollmentStatus, SortDir, StudentListItem } from "@/lib/api/types";
import { useDashboard } from "@/lib/hooks/use-dashboard";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
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

export default function StudentsPage() {
  const [rawQuery, setRawQuery] = useState("");
  const query = useDebouncedValue(rawQuery.trim(), 300);
  const [filter, setFilter] = useState<"all" | EnrollmentStatus>("all");
  const { sort, dir, onSort } = useListSort("name", SORT_DEFAULT_DIR);
  const [invite, setInvite] = useState<Invite | null>(null);

  const { dashboard } = useDashboard();
  const { items, total, isLoading, isLoadingMore, error, reachedEnd, loadMore, mutate } =
    useStudents({ q: query || undefined, sort, dir, status: filter });

  const counts = dashboard?.students;
  const chips: ChipItem[] = [
    { id: "all", label: "All", count: counts?.total },
    { id: "enrolled", label: "Enrolled", count: counts?.enrolled },
    { id: "pending", label: "Pending", count: counts?.pending },
    { id: "failed", label: "Failed", count: counts?.failed },
  ];

  const isInitialLoading = isLoading && items.length === 0;
  const isFiltering = filter !== "all" || query.length > 0;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Students"
        description="Enroll students so they receive the photos they appear in."
        actions={
          <div className="flex flex-wrap gap-2">
            <BulkImportDialog onImported={() => mutate()} />
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
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <FilterChips
              items={chips}
              activeId={filter}
              onSelect={(id) => setFilter(id as "all" | EnrollmentStatus)}
              ariaLabel="Filter by enrollment status"
            />
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
                            <span className="font-medium text-ink hover:underline">{student.name}</span>
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
