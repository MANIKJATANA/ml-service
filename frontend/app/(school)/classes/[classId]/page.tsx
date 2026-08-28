"use client";

import { UserPlus, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { RoleGate } from "@/components/role-gate";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { LoadMore } from "@/components/ui/load-more";
import { PageHeader } from "@/components/ui/page-header";
import { SearchInput } from "@/components/ui/search-input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import {
  assignStudentsToClass,
  assignStudentsToClassByEmail,
  assignTeachersToClass,
  getClassTeachers,
  removeClassTeacher,
  setStudentClass,
} from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import { useClasses } from "@/lib/hooks/use-classes";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { useStaff } from "@/lib/hooks/use-staff";
import { useStudents } from "@/lib/hooks/use-students";

type Picked = { id: string; name: string; email: string };

/** Add students to a class (BP11a). The search list is rendered INLINE in the dialog (not a
 *  portaled popover) so it scrolls under the modal's scroll-lock; picks accumulate as chips,
 *  then one bulk call assigns them. `excludeIds` hides students already in the class. */
function AddStudentsDialog({
  classId,
  excludeIds,
  onAdded,
}: {
  classId: string;
  excludeIds: Set<string>;
  onAdded: () => void;
}) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [rawQuery, setRawQuery] = useState("");
  const query = useDebouncedValue(rawQuery.trim(), 300);
  const [picked, setPicked] = useState<Picked[]>([]);
  const [saving, setSaving] = useState(false);
  const { items } = useStudents({ q: query || undefined });

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      setRawQuery("");
      setPicked([]);
    }
  }

  const pickedIds = new Set(picked.map((p) => p.id));
  // `excludeIds` is the roster's *loaded* pages (the roster is paginated), so a member on an
  // unloaded page could still surface here — harmless: re-assigning the same class is an
  // idempotent no-op UPDATE. Server-side exclusion is the real fix (out of scope for BP11a).
  const results = items.filter((s) => !excludeIds.has(s.id) && !pickedIds.has(s.id));

  async function onAdd() {
    if (picked.length === 0) return;
    setSaving(true);
    try {
      await assignStudentsToClass(
        classId,
        picked.map((p) => p.id),
      );
      toast(
        `Added ${picked.length} student${picked.length === 1 ? "" : "s"} to the class.`,
        "success",
      );
      onAdded();
      handleOpenChange(false);
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button>
          <UserPlus className="size-4" aria-hidden="true" />
          Add students
        </Button>
      </DialogTrigger>
      <DialogContent
        title="Add students to class"
        description="Search by name or email, pick the students, then add them all at once."
      >
        <div className="flex flex-col gap-3">
          <SearchInput
            value={rawQuery}
            onChange={setRawQuery}
            placeholder="Search name or email…"
            className="sm:max-w-none"
          />
          {picked.length > 0 ? (
            <ul className="flex flex-wrap gap-1.5" aria-label="Selected students">
              {picked.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    onClick={() => setPicked((cur) => cur.filter((x) => x.id !== p.id))}
                    className="inline-flex items-center gap-1 rounded-full border border-hairline bg-surface-2 px-2.5 py-1 text-body-sm text-ink hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label={`Remove ${p.name} from selection`}
                  >
                    {p.name}
                    <X className="size-3.5" aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          <ul className="max-h-64 divide-y divide-hairline overflow-y-auto overscroll-contain rounded-button border border-hairline">
            {results.length === 0 ? (
              <li className="px-3 py-3 text-body-sm text-ink-secondary">
                {query ? "No matching students." : "Search to find students to add."}
              </li>
            ) : (
              results.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() =>
                      setPicked((cur) => [...cur, { id: s.id, name: s.name, email: s.email }])
                    }
                    className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  >
                    <span className="min-w-0 flex-1 truncate text-body-sm text-ink">{s.name}</span>
                    <span className="min-w-0 shrink truncate text-body-sm text-ink-secondary">
                      {s.email}
                    </span>
                  </button>
                </li>
              ))
            )}
          </ul>
          {/* Announce result availability to screen readers without reading the whole list. */}
          <span role="status" aria-live="polite" className="sr-only">
            {query ? `${results.length} student${results.length === 1 ? "" : "s"} found` : ""}
          </span>
          <div className="mt-1 flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="secondary">
                Cancel
              </Button>
            </DialogClose>
            <Button onClick={onAdd} loading={saving} disabled={picked.length === 0}>
              Add {picked.length > 0 ? picked.length : ""} to class
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

const MAX_EMAILS = 1000; // mirrors the backend _MAX_ASSIGN cap (a friendlier guard than a 422)

/** Bulk-assign students to a class by pasting a list of emails (BP24) — no 800 search-and-clicks.
 *  The emails are resolved server-side; the result shows how many were added + which emails
 *  matched no student (kept in the box to fix + retry). */
function PasteEmailsDialog({
  classId,
  onAdded,
}: {
  classId: string;
  onAdded: () => void;
}) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [unmatched, setUnmatched] = useState<string[] | null>(null);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      setText("");
      setUnmatched(null);
    }
  }

  // Split on commas / semicolons / whitespace / newlines; trim; drop blanks.
  const emails = text
    .split(/[\s,;]+/)
    .map((e) => e.trim())
    .filter(Boolean);

  async function onAssign() {
    if (emails.length === 0) return;
    if (emails.length > MAX_EMAILS) {
      toast(`Up to ${MAX_EMAILS} emails at a time — paste fewer and try again.`, "error");
      return;
    }
    setSaving(true);
    setUnmatched(null);
    try {
      const { assigned, unmatched: miss } = await assignStudentsToClassByEmail(classId, emails);
      onAdded();
      if (miss.length === 0) {
        toast(`Added ${assigned} student${assigned === 1 ? "" : "s"} to the class.`, "success");
        handleOpenChange(false);
      } else {
        // Some emails matched no student — keep the dialog open + leave only those to fix.
        toast(
          assigned === 0
            ? "No emails matched a student in this school — check for typos."
            : `Added ${assigned} student${assigned === 1 ? "" : "s"}; ${miss.length} email${miss.length === 1 ? "" : "s"} didn't match.`,
          "info",
        );
        setUnmatched(miss);
        setText(miss.join("\n"));
      }
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="secondary">Paste emails</Button>
      </DialogTrigger>
      <DialogContent
        title="Add students by email"
        description="Paste a list of student emails (one per line, or comma-separated) — they're all added to this class at once."
      >
        <div className="flex flex-col gap-3">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={8}
            aria-label="Student emails"
            placeholder={"ada@school.edu\ngrace@school.edu\n…"}
            className="w-full rounded-button border border-hairline bg-canvas px-3 py-2 text-body text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <p className="text-body-sm text-ink-secondary" role="status">
            {emails.length} email{emails.length === 1 ? "" : "s"} ready.
          </p>
          {unmatched && unmatched.length > 0 ? (
            <div className="rounded-card border border-hairline bg-surface p-3" role="status">
              <p className="text-body-sm font-medium text-ink">
                {unmatched.length} didn&apos;t match a student in this school:
              </p>
              <p className="mt-1 break-words text-body-sm text-ink-secondary">
                {unmatched.join(", ")}
              </p>
            </div>
          ) : null}
          <div className="mt-1 flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="secondary">
                Cancel
              </Button>
            </DialogClose>
            <Button onClick={onAssign} loading={saving} disabled={emails.length === 0}>
              Add {emails.length > 0 ? emails.length : ""} to class
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

type PickedTeacher = { id: string; email: string };

/** Assign teachers to a class (BP11c) — mirrors AddStudentsDialog: an inline searchable list
 *  (not a portaled popover) of the school's teachers, picks accumulate, then one bulk call. */
function AssignTeachersDialog({
  classId,
  excludeIds,
  onAssigned,
}: {
  classId: string;
  excludeIds: Set<string>;
  onAssigned: () => void;
}) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [rawQuery, setRawQuery] = useState("");
  const query = useDebouncedValue(rawQuery.trim(), 300);
  const [picked, setPicked] = useState<PickedTeacher[]>([]);
  const [saving, setSaving] = useState(false);
  const { items } = useStaff({ q: query || undefined });

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      setRawQuery("");
      setPicked([]);
    }
  }

  const pickedIds = new Set(picked.map((p) => p.id));
  const results = items.filter((t) => !excludeIds.has(t.id) && !pickedIds.has(t.id));

  async function onAssign() {
    if (picked.length === 0) return;
    setSaving(true);
    try {
      await assignTeachersToClass(
        classId,
        picked.map((p) => p.id),
      );
      toast(
        `Assigned ${picked.length} teacher${picked.length === 1 ? "" : "s"} to the class.`,
        "success",
      );
      onAssigned();
      handleOpenChange(false);
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="secondary" size="sm">
          <UserPlus className="size-4" aria-hidden="true" />
          Assign teachers
        </Button>
      </DialogTrigger>
      <DialogContent
        title="Assign teachers to class"
        description="Pick the teachers who manage this class. They'll see its students and events focused first."
      >
        <div className="flex flex-col gap-3">
          <SearchInput
            value={rawQuery}
            onChange={setRawQuery}
            placeholder="Search teacher email…"
            className="sm:max-w-none"
          />
          {picked.length > 0 ? (
            <ul className="flex flex-wrap gap-1.5" aria-label="Selected teachers">
              {picked.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    onClick={() => setPicked((cur) => cur.filter((x) => x.id !== p.id))}
                    className="inline-flex items-center gap-1 rounded-full border border-hairline bg-surface-2 px-2.5 py-1 text-body-sm text-ink hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label={`Remove ${p.email} from selection`}
                  >
                    {p.email}
                    <X className="size-3.5" aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          <ul className="max-h-64 divide-y divide-hairline overflow-y-auto overscroll-contain rounded-button border border-hairline">
            {results.length === 0 ? (
              <li className="px-3 py-3 text-body-sm text-ink-secondary">
                {query ? "No matching teachers." : "Search to find teachers to assign."}
              </li>
            ) : (
              results.map((t) => (
                <li key={t.id}>
                  <button
                    type="button"
                    onClick={() => setPicked((cur) => [...cur, { id: t.id, email: t.email }])}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  >
                    <span className="min-w-0 flex-1 truncate text-body-sm text-ink">{t.email}</span>
                  </button>
                </li>
              ))
            )}
          </ul>
          <span role="status" aria-live="polite" className="sr-only">
            {query ? `${results.length} teacher${results.length === 1 ? "" : "s"} found` : ""}
          </span>
          <div className="mt-1 flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="secondary">
                Cancel
              </Button>
            </DialogClose>
            <Button onClick={onAssign} loading={saving} disabled={picked.length === 0}>
              Assign {picked.length > 0 ? picked.length : ""}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** The teachers who manage this class (BP11c). School-admin only — a card of teacher chips with
 *  a remove action + the assign dialog. Keyed on the class so an assign/remove refreshes it. */
function TeachersSection({ classId }: { classId: string }) {
  const { toast } = useToast();
  const { data, isLoading, mutate } = useSWR(`class-teachers:${classId}`, () =>
    getClassTeachers(classId),
  );
  const teachers = data ?? [];

  // Also refresh the Staff page's per-teacher "Classes" chips (a different SWR namespace) so a
  // change here isn't stale if both surfaces are open.
  function refreshBoth() {
    void mutate();
    void globalMutate((k) => typeof k === "string" && k.startsWith("staff-classes:"));
  }

  async function onRemove(teacherId: string, email: string) {
    try {
      await removeClassTeacher(classId, teacherId);
      toast(`Removed ${email} from the class.`, "success");
      refreshBoth();
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    }
  }

  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-body font-medium text-ink">Teachers</h2>
        <AssignTeachersDialog
          classId={classId}
          excludeIds={new Set(teachers.map((t) => t.id))}
          onAssigned={refreshBoth}
        />
      </div>
      {isLoading ? (
        <Skeleton className="h-8 w-48" />
      ) : teachers.length === 0 ? (
        <p className="text-body-sm text-ink-secondary">
          No teachers assigned. Assign teachers so they see this class focused first.
        </p>
      ) : (
        <ul className="flex flex-wrap gap-1.5" aria-label="Assigned teachers">
          {teachers.map((t) => (
            <li key={t.id}>
              <span className="inline-flex items-center gap-1 rounded-full border border-hairline bg-surface-2 px-2.5 py-1 text-body-sm text-ink">
                {t.email}
                <button
                  type="button"
                  onClick={() => onRemove(t.id, t.email)}
                  className="rounded-full text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  aria-label={`Remove ${t.email} from class`}
                >
                  <X className="size-3.5" aria-hidden="true" />
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ClassDetailInner({ classId }: { classId: string }) {
  const { toast } = useToast();
  const { classes, isLoading: classesLoading, mutate: mutateClasses } = useClasses();
  const cls = classes.find((c) => c.id === classId);

  const {
    items,
    total,
    isLoading,
    isLoadingMore,
    error,
    reachedEnd,
    loadMore,
    mutate,
  } = useStudents({ student_group_id: classId });

  function refresh() {
    void mutate();
    void mutateClasses(); // keep the class list's member count in sync
  }

  async function onRemove(studentId: string, name: string) {
    try {
      await setStudentClass(studentId, null);
      toast(`Removed ${name} from the class.`, "success");
      refresh();
      void globalMutate("students");
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    }
  }

  const notFound = !classesLoading && cls === undefined;

  return (
    <div className="flex flex-col gap-6">
      <Breadcrumb
        items={[{ label: "Classes", href: "/classes" }, { label: cls?.name ?? "Class" }]}
      />

      {notFound ? (
        <EmptyState
          role="alert"
          title="Class not found"
          description="It may have been deleted."
          action={
            <Link href="/classes" className={buttonVariants({ variant: "secondary" })}>
              Back to classes
            </Link>
          }
        />
      ) : (
        <>
          <PageHeader
            title={cls?.name ?? "Class"}
            description={
              cls
                ? [cls.grade, cls.section].filter(Boolean).join(" · ") || undefined
                : undefined
            }
            actions={
              <div className="flex flex-wrap gap-2">
                <PasteEmailsDialog classId={classId} onAdded={refresh} />
                <AddStudentsDialog
                  classId={classId}
                  excludeIds={new Set(items.map((s) => s.id))}
                  onAdded={refresh}
                />
              </div>
            }
          />

          <TeachersSection classId={classId} />

          {isLoading && items.length === 0 ? (
            <Card role="status" aria-label="Loading roster" className="flex flex-col gap-2 p-4">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </Card>
          ) : error ? (
            <EmptyState
              role="alert"
              title="Couldn't load the roster"
              description="Something went wrong reaching the server."
              action={
                <Button variant="secondary" onClick={() => mutate()}>
                  Retry
                </Button>
              }
            />
          ) : total === 0 ? (
            <EmptyState
              title="No students in this class"
              description="Add students to build the class roster."
              action={
                <div className="flex flex-wrap justify-center gap-2">
                  <PasteEmailsDialog classId={classId} onAdded={refresh} />
                  <AddStudentsDialog
                    classId={classId}
                    excludeIds={new Set()}
                    onAdded={refresh}
                  />
                </div>
              }
            />
          ) : (
            <>
              <Card className="overflow-hidden">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Student</TableHead>
                      <TableHead>Email</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((s) => (
                      <TableRow key={s.id} className="transition-colors hover:bg-surface">
                        <TableCell>
                          <Link
                            href={`/students/${s.id}`}
                            className="font-medium text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          >
                            {s.name}
                          </Link>
                        </TableCell>
                        <TableCell className="text-ink-secondary">{s.email}</TableCell>
                        <TableCell>
                          <div className="flex justify-end">
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={`Remove ${s.name} from class`}
                              onClick={() => onRemove(s.id, s.name)}
                            >
                              Remove
                            </Button>
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
        </>
      )}
    </div>
  );
}

export default function ClassDetailPage() {
  const { classId } = useParams<{ classId: string }>();
  return (
    <RoleGate allow={["school_admin"]}>
      <ClassDetailInner classId={classId} />
    </RoleGate>
  );
}
