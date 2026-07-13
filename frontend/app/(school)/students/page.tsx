"use client";

import { GraduationCap, UserPlus } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useMemo, useState } from "react";

import { StudentAvatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { FileDropzone } from "@/components/ui/file-dropzone";
import { type ChipItem, FilterChips } from "@/components/gallery/filter-chips";
import { Input } from "@/components/ui/input";
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
import type { EnrollmentStatus, StudentListItem } from "@/lib/api/types";
import { useStudents } from "@/lib/hooks/use-students";
import { useSort } from "@/lib/hooks/use-sort";
import { ENROLL_LABEL, ENROLL_TONE } from "@/lib/students/enrollment";

const SORT: Record<string, (s: StudentListItem) => string | number> = {
  name: (s) => s.name.toLowerCase(),
  appearances: (s) => s.appearance_count,
};

function CreateStudentDialog({ onCreated }: { onCreated: () => void }) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploadedPath, setUploadedPath] = useState<string | null>(null); // survives a failed create
  const [progress, setProgress] = useState<number | null>(null); // non-null while uploading
  const [submitting, setSubmitting] = useState(false);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      setName("");
      setEmail("");
      setPassword("");
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
      // Upload the photo straight to Supabase, then create the student with its path.
      // Memoize the uploaded path so fixing a rejected field (e.g. a duplicate email)
      // and resubmitting doesn't re-upload the same photo.
      let objectPath = uploadedPath;
      if (!objectPath) {
        setProgress(0);
        objectPath = await uploadReferencePhoto(file, setProgress);
        setProgress(null);
        setUploadedPath(objectPath);
      }
      await createStudent(name.trim(), email.trim(), password, objectPath);
      toast("Student created.", "success");
      onCreated();
      handleOpenChange(false);
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
        description="Creates a student login and enrolls their face from the reference photo."
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
          <Field label="Temporary password" htmlFor="student-password" hint="At least 8 characters.">
            <Input
              id="student-password"
              type="text"
              autoComplete="off"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
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

export default function StudentsPage() {
  const { students, isLoading, error, mutate } = useStudents();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | EnrollmentStatus>("all");

  const chips: ChipItem[] = useMemo(() => {
    const all = students ?? [];
    const by = (s: EnrollmentStatus) => all.filter((x) => x.enrollment_status === s).length;
    return [
      { id: "all", label: "All", count: all.length },
      { id: "enrolled", label: "Enrolled", count: by("enrolled") },
      { id: "pending", label: "Pending", count: by("pending") },
      { id: "failed", label: "Failed", count: by("failed") },
    ];
  }, [students]);

  const filtered = useMemo(() => {
    let rows = students ?? [];
    if (filter !== "all") rows = rows.filter((s) => s.enrollment_status === filter);
    const q = query.trim().toLowerCase();
    if (q) {
      rows = rows.filter(
        (s) => s.name.toLowerCase().includes(q) || s.email.toLowerCase().includes(q),
      );
    }
    return rows;
  }, [students, filter, query]);

  const { sorted, sortKey, sortDir, toggle } = useSort(filtered, SORT, "name");

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Students"
        description="Enroll students so they receive the photos they appear in."
        actions={<CreateStudentDialog onCreated={() => mutate()} />}
      />

      {isLoading ? (
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
      ) : !students || students.length === 0 ? (
        <EmptyState
          icon={<GraduationCap className="size-8" aria-hidden="true" />}
          title="No students yet"
          description="Add a student and upload their reference photo to enroll them."
          action={<CreateStudentDialog onCreated={() => mutate()} />}
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
            <SearchInput value={query} onChange={setQuery} placeholder="Search name or email…" />
          </div>
          {sorted.length === 0 ? (
            <EmptyState title="No matching students" description="Try a different search or filter." />
          ) : (
            <Card className="overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow>
                    <SortableHead
                      label="Student"
                      sortKey="name"
                      activeKey={sortKey}
                      dir={sortDir}
                      onSort={toggle}
                    />
                    <TableHead>Email</TableHead>
                    <SortableHead
                      label="Appears in"
                      sortKey="appearances"
                      activeKey={sortKey}
                      dir={sortDir}
                      onSort={toggle}
                    />
                    <TableHead>Enrollment</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sorted.map((student) => (
                    <TableRow key={student.id} className="transition-colors hover:bg-surface">
                      <TableCell>
                        <Link
                          href={`/students/${student.id}`}
                          className="flex items-center gap-3 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          <StudentAvatar name={student.name} />
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
                        <StatusPill tone={ENROLL_TONE[student.enrollment_status]}>
                          {ENROLL_LABEL[student.enrollment_status]}
                        </StatusPill>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
