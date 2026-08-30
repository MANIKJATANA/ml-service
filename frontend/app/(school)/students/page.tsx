"use client";

import { Ban, CircleCheck, GraduationCap, KeyRound, RotateCcw, Trash2, UserPlus } from "lucide-react";
import Link from "next/link";
import { type FormEvent, Suspense, useEffect, useState } from "react";

import {
  BulkCredentialsDialog,
  type CredentialRow,
} from "@/components/credentials/bulk-credentials-dialog";
import { StudentAvatar } from "@/components/ui/avatar";
import { Highlight } from "@/components/ui/highlight";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { FileDropzone } from "@/components/ui/file-dropzone";
import { DelegationBanner } from "@/components/delegation/delegation-banner";
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
import {
  assignStudentsToClass,
  bulkDeleteStudents,
  bulkRemoveStudentsFromClass,
  bulkResendStudentInvites,
  bulkSetStudentStatus,
  createStudent,
  enrollStudent,
  getStudentIds,
  getStudents,
  type StudentFilterParams,
} from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import { uploadReferencePhoto } from "@/lib/api/upload";
import type {
  BulkActionResponse,
  EnrollmentStatus,
  SortDir,
  StudentListItem,
} from "@/lib/api/types";
import { useClasses } from "@/lib/hooks/use-classes";
import { useDashboard } from "@/lib/hooks/use-dashboard";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { useMe } from "@/lib/hooks/use-me";
import { useMyClasses } from "@/lib/hooks/use-my-classes";
import { useUrlListSort } from "@/lib/hooks/use-sort";
import { useStudentReferencePhoto } from "@/lib/hooks/use-student-reference-photo";
import { useStudents } from "@/lib/hooks/use-students";
import { useUrlParams } from "@/lib/hooks/use-url-state";
import {
  ENROLL_FAILURE_SHORT,
  enrollDisplay,
} from "@/lib/students/enrollment";

// The default sort direction when a column is first selected (BP9): names A→Z, counts
// most-first. Clicking an already-active column toggles the direction.
const SORT_DEFAULT_DIR: Record<string, SortDir> = {
  name: "asc",
  appearance_count: "desc",
};

/** BP27 multi-select: either an explicit hand-picked set ("ids") or the whole matching set
 *  fetched from the server ("all", so a bulk action spans pages). */
type Selection =
  | { mode: "ids"; ids: Set<string> }
  | { mode: "all"; ids: string[]; total: number };

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
          {/* A08: say what the reference photo is FOR — it enrolls the student's face. */}
          <FileDropzone
            file={file}
            onFileChange={(next) => {
              setFile(next);
              setUploadedPath(null); // a new file must be re-uploaded
            }}
            disabled={submitting}
            hint="This photo enrolls the student's face for matching — a clear, front-facing photo works best (up to 30 MB)."
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

function StudentsContent() {
  // BP25: filters live in the URL (shareable + Back-safe) via useUrlParams.
  const { get, set } = useUrlParams();
  const urlQ = get("q");
  const [rawQuery, setRawQuery] = useState(urlQ);
  const [prevUrlQ, setPrevUrlQ] = useState(urlQ);
  if (urlQ !== prevUrlQ) {
    setPrevUrlQ(urlQ);
    setRawQuery(urlQ);
  }
  const debounced = useDebouncedValue(rawQuery.trim(), 300);
  // Write only once the debounce settles to the current input (BP25 R1 fix: a Back that drops
  // `q` must not have the lagging debounce re-add it for ~300ms).
  useEffect(() => {
    if (debounced === rawQuery.trim() && debounced !== urlQ) set({ q: debounced || null });
  }, [debounced, rawQuery, urlQ, set]);
  const query = urlQ;
  const statusParam = get("status", "all");
  const filter: "all" | EnrollmentStatus =
    statusParam === "enrolled" || statusParam === "pending" || statusParam === "failed"
      ? statusParam
      : "all";
  const classFilter = get("class", ""); // "" = all classes (BP11a)
  const focus = get("mine", "1") !== "0"; // BP11c: default a teacher to their classes
  // BP23: a single "activity" select drives the two independent server filters (login/opened).
  const loginNever = get("login") === "never";
  const openedNever = get("opened") === "never";
  const activity = loginNever ? "never_signed_in" : openedNever ? "never_opened" : "";
  const { sort, dir, onSort } = useUrlListSort("name", SORT_DEFAULT_DIR, { get, set });
  const [invite, setInvite] = useState<Invite | null>(null);

  const { dashboard, mutate: mutateDashboard } = useDashboard();
  const { classes } = useClasses();
  const { user } = useMe();
  const isTeacher = user?.role === "teacher";
  const { classes: myClasses } = useMyClasses(isTeacher);
  // BP29 (R4-T05): mark a teacher's own classes in the filter dropdown so "my class" is legible
  // (options can't be richly styled — a text suffix only).
  const mine = new Set(myClasses.map((c) => c.id));
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
      login: loginNever ? "never" : undefined,
      opened: openedNever ? "never" : undefined,
    });

  const { toast } = useToast();
  // BP27: bulk enable/disable/delete + assign-to-class over a multi-select. The selection is a
  // discriminated model — "ids" (an explicit set, stale-safe: only ids still on the loaded page
  // are acted on) or "all" (a snapshot of EVERY matching id from the server, so an action can
  // span pages). Reset to empty whenever the filter/search/sort changes (the same queryKey the
  // list resets on) so an "all" snapshot never carries across filters.
  const [selection, setSelection] = useState<Selection>({ mode: "ids", ids: new Set() });
  const [bulkClassId, setBulkClassId] = useState("");
  // Which bulk op is in flight (null = idle) — drives the disabled/double-submit guard AND a
  // spinner on the *clicked* button (not every button). `bulkBusy` is derived, one source of truth.
  const [bulkAction, setBulkAction] = useState<
    "disable" | "enable" | "delete" | "assign" | "removeClass" | "resend" | null
  >(null);
  const bulkBusy = bulkAction !== null;
  const [selectingAll, setSelectingAll] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  // BP27b: the shown-once temp passwords from a bulk resend (null = dialog closed → drops them).
  const [bulkCreds, setBulkCreds] = useState<CredentialRow[] | null>(null);
  // The filter the list is currently showing — kept param-identical so getStudentIds' scan
  // matches exactly (BP27 select-all-matching).
  const currentFilters: StudentFilterParams = {
    q: query || undefined,
    status: filter,
    student_group_id: activeClassFilter || undefined,
    mine: focusOn,
    login: loginNever ? "never" : undefined,
    opened: openedNever ? "never" : undefined,
  };
  const filterKey = JSON.stringify([
    query,
    filter,
    activeClassFilter,
    focusOn,
    loginNever,
    openedNever,
  ]);
  // Reset the selection whenever the filter/search changes (NOT sort/dir — re-sorting only reorders
  // the same matching set, so a hand-picked selection should survive it) — adjust-state-during-render (the
  // codebase's stale-safe pattern, mirroring `rawQuery`'s reset above), not an effect, so an
  // "all" snapshot never carries across filters and it happens in the same render as the change.
  const [prevFilterKey, setPrevFilterKey] = useState(filterKey);
  if (filterKey !== prevFilterKey) {
    setPrevFilterKey(filterKey);
    setSelection({ mode: "ids", ids: new Set() });
  }

  const loadedIds = new Set(items.map((s) => s.id));
  // The ids a bulk action will actually target: for "ids", only those still loaded (stale-safe);
  // for "all", the whole server snapshot.
  const targetIds =
    selection.mode === "all"
      ? selection.ids
      : [...selection.ids].filter((id) => loadedIds.has(id));
  const selectedCount = targetIds.length;
  const allOnPageSelected =
    items.length > 0 &&
    (selection.mode === "all" || items.every((s) => selection.ids.has(s.id)));
  const isSelected = (id: string) =>
    selection.mode === "all" ? selection.ids.includes(id) : selection.ids.has(id);
  function clearSelection() {
    setSelection({ mode: "ids", ids: new Set() });
    setBulkClassId("");
  }
  function toggleStudent(id: string) {
    // Toggling a row leaves "all" mode — the user is now hand-picking again (starting from the
    // current selection, whether that was an "all" snapshot or an explicit set).
    setSelection((cur) => {
      const base = new Set(cur.ids); // Set(string[]) and Set(Set) both work
      if (base.has(id)) base.delete(id);
      else base.add(id);
      return { mode: "ids", ids: base };
    });
  }
  function toggleAllOnPage() {
    setSelection((cur) => {
      if (cur.mode === "ids" && !allOnPageSelected) {
        const next = new Set(cur.ids);
        items.forEach((s) => next.add(s.id));
        return { mode: "ids", ids: next };
      }
      // Everything on the page (or "all") is selected → clear.
      return { mode: "ids", ids: new Set() };
    });
  }
  async function selectAllMatching() {
    setSelectingAll(true);
    try {
      const { ids, total: matched } = await getStudentIds(currentFilters);
      setSelection({ mode: "all", ids, total: matched });
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setSelectingAll(false);
    }
  }

  /** Count `ok`/`error` from a bulk response and toast honestly. Returns nothing — the caller
   *  refreshes the list + dashboard and clears the selection. */
  function reportBulk(resp: BulkActionResponse, verb: string, failVerb = "updated"): void {
    const total = resp.results.length;
    const ok = resp.results.filter((r) => r.status === "ok").length;
    const failed = total - ok;
    if (failed === 0) {
      toast(`${verb} ${ok} ${ok === 1 ? "student" : "students"}.`, "success");
    } else {
      toast(
        `${verb} ${ok} of ${total} — ${failed} couldn't be ${failVerb}.`,
        ok > 0 ? "warning" : "error",
      );
    }
  }

  async function afterBulkMutation() {
    clearSelection();
    await mutate();
    void mutateDashboard();
  }

  async function assignBulk() {
    if (!bulkClassId || selectedCount === 0) return;
    setBulkAction("assign");
    try {
      const { assigned } = await assignStudentsToClass(bulkClassId, targetIds);
      toast(
        `Assigned ${assigned} ${assigned === 1 ? "student" : "students"} to the class.`,
        "success",
      );
      await afterBulkMutation();
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setBulkAction(null);
    }
  }

  async function removeFromClassBulk() {
    if (selectedCount === 0) return;
    setBulkAction("removeClass");
    try {
      const resp = await bulkRemoveStudentsFromClass(targetIds);
      // "Cleared class for" (not "Removed") — the backend returns ok even for a student who wasn't
      // in a class (a no-op clear), so "Removed N" would over-claim.
      reportBulk(resp, "Cleared class for", "updated");
      await afterBulkMutation();
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setBulkAction(null);
    }
  }

  async function setStatusBulk(status: "active" | "disabled") {
    if (selectedCount === 0) return;
    setBulkAction(status === "disabled" ? "disable" : "enable");
    try {
      const resp = await bulkSetStudentStatus(targetIds, status);
      reportBulk(resp, status === "disabled" ? "Disabled" : "Enabled");
      await afterBulkMutation();
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setBulkAction(null);
    }
  }

  async function deleteBulk() {
    if (selectedCount === 0) return;
    setBulkAction("delete");
    try {
      const resp = await bulkDeleteStudents(targetIds);
      reportBulk(resp, "Deleted", "deleted");
      await afterBulkMutation();
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setBulkAction(null);
      setDeleteConfirm(false);
    }
  }

  async function resendCreds() {
    if (selectedCount === 0) return;
    setBulkAction("resend");
    try {
      const resp = await bulkResendStudentInvites(targetIds);
      const sent = resp.results.filter((r) => r.status === "sent").length;
      const failed = resp.results.length - sent;
      // Show the ONE-TIME passwords (present only on `sent` rows) in the shared dialog.
      setBulkCreds(
        resp.results.map((r) => ({
          label: r.email,
          status: r.status,
          tempPassword: r.temp_password,
        })),
      );
      toast(
        failed === 0
          ? `Sent ${sent} new password${sent === 1 ? "" : "s"}.`
          : `Sent ${sent} of ${resp.results.length} — ${failed} couldn't be sent.`,
        failed === 0 ? "success" : sent > 0 ? "warning" : "error",
      );
      // A resend changes no list-visible field (photos/matches untouched), so just clear the
      // selection — NOT afterBulkMutation (no list/dashboard refresh needed).
      clearSelection();
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setBulkAction(null);
    }
  }

  const counts = dashboard?.students;
  const chips: ChipItem[] = [
    { id: "all", label: "All", count: counts?.total },
    { id: "enrolled", label: "Enrolled", count: counts?.enrolled },
    { id: "pending", label: "Pending", count: counts?.pending },
    { id: "failed", label: "Failed", count: counts?.failed },
  ];

  const isInitialLoading = isLoading && items.length === 0;
  const isFiltering =
    filter !== "all" ||
    query.length > 0 ||
    activeClassFilter !== "" ||
    focusOn ||
    activity !== "";

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
            <CreateStudentDialog
              onCreated={() => {
                mutate();
                void mutateDashboard(); // advance the setup checklist without waiting on the poll
              }}
              onInvited={setInvite}
            />
          </div>
        }
      />

      {/* BP29 (R4-T01): tell an un-delegated teacher why their lists show all classes. Mounted
          above the conditional block so it shows in every state (self-gates to teacher + 0 classes). */}
      <DelegationBanner />

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
              <CreateStudentDialog
                onCreated={() => {
                  mutate();
                  void mutateDashboard(); // advance the setup checklist without waiting on the poll
                }}
                onInvited={setInvite}
              />
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
            onSelect={(id) => set({ status: id === "all" ? null : id })}
            ariaLabel="Filter by enrollment status"
          />
          {/* Row 2: the scope toggle + class filter (left) and search (right). */}
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              {canFocus ? (
                <FocusToggle value={focus} onChange={(next) => set({ mine: next ? null : "0" })} />
              ) : null}
              {classes.length > 0 ? (
                <select
                  aria-label="Filter by class"
                  value={activeClassFilter}
                  onChange={(e) => set({ class: e.target.value || null })}
                  className="h-10 rounded-button border border-hairline bg-canvas px-3 text-body text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <option value="">All classes</option>
                  {classes.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                      {mine.has(c.id) ? " (my class)" : ""}
                    </option>
                  ))}
                </select>
              ) : null}
              {/* BP23: the "which students?" activity filter — one select drives login/opened. */}
              <select
                aria-label="Filter by activity"
                value={activity}
                onChange={(e) => {
                  const v = e.target.value;
                  set({
                    login: v === "never_signed_in" ? "never" : null,
                    opened: v === "never_opened" ? "never" : null,
                  });
                }}
                className="h-10 rounded-button border border-hairline bg-canvas px-3 text-body text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <option value="">All activity</option>
                <option value="never_signed_in">Never signed in</option>
                <option value="never_opened">Never opened photos</option>
              </select>
            </div>
            <SearchInput value={rawQuery} onChange={setRawQuery} placeholder="Search name or email…" />
          </div>
          {/* BP27: the multi-select action bar — enable/disable/delete (+ assign-to-class when the
              school has classes). "Select all N matching" flips to acting on every matching
              student (spans pages), not just the loaded page. */}
          {selectedCount > 0 ? (
            <div className="flex flex-col gap-3 rounded-card border border-hairline bg-surface px-4 py-3">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span role="status" className="text-body-sm font-medium text-ink">
                  {selection.mode === "all"
                    ? `All ${selection.total} selected`
                    : `${selectedCount} selected`}
                  {bulkBusy ? " · working…" : ""}
                </span>
                {/* Offer "select all matching" once the whole loaded page is picked but more rows
                    match than are loaded; once in "all" mode, offer Clear. */}
                {selection.mode === "all" ? (
                  <Button size="sm" variant="ghost" onClick={clearSelection} disabled={bulkBusy}>
                    Clear
                  </Button>
                ) : allOnPageSelected && total > items.length ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={selectAllMatching}
                    loading={selectingAll}
                    disabled={selectingAll || bulkBusy}
                  >
                    Select all {total} matching
                  </Button>
                ) : (
                  <Button size="sm" variant="ghost" onClick={clearSelection} disabled={bulkBusy}>
                    Clear
                  </Button>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => setStatusBulk("disabled")}
                  loading={bulkAction === "disable"}
                  disabled={bulkBusy}
                >
                  <Ban className="size-4" aria-hidden="true" />
                  Disable
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => setStatusBulk("active")}
                  loading={bulkAction === "enable"}
                  disabled={bulkBusy}
                >
                  <CircleCheck className="size-4" aria-hidden="true" />
                  Enable
                </Button>
                {/* BP27b: re-issue a fresh one-time password to each selected student (recovery
                    without the destructive delete). The shown-once passwords open in a dialog. */}
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={resendCreds}
                  loading={bulkAction === "resend"}
                  disabled={bulkBusy}
                >
                  <KeyRound className="size-4" aria-hidden="true" />
                  Resend credentials
                </Button>
                {classes.length > 0 ? (
                  <>
                    <div className="flex items-center gap-2">
                      <select
                        aria-label="Class to assign to"
                        value={bulkClassId}
                        onChange={(e) => setBulkClassId(e.target.value)}
                        className="h-9 rounded-button border border-hairline bg-canvas px-3 text-body-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <option value="">Assign to class…</option>
                        {classes.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.name}
                          </option>
                        ))}
                      </select>
                      <Button
                        size="sm"
                        onClick={assignBulk}
                        loading={bulkAction === "assign"}
                        disabled={!bulkClassId || bulkBusy}
                      >
                        Assign
                      </Button>
                    </div>
                    {/* BP27c: clear the selected students' class (R4-A10) — the inverse of Assign,
                        so a mis-assignment is a two-way door. */}
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={removeFromClassBulk}
                      loading={bulkAction === "removeClass"}
                      disabled={bulkBusy}
                    >
                      Remove from class
                    </Button>
                  </>
                ) : null}
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => setDeleteConfirm(true)}
                  disabled={bulkBusy}
                >
                  <Trash2 className="size-4" aria-hidden="true" />
                  Delete
                </Button>
              </div>
            </div>
          ) : null}
          {total === 0 ? (
            <EmptyState title="No matching students" description="Try a different search or filter." />
          ) : (
            <>
              <Card className="overflow-hidden">
                <Table>
                  <TableHeader>
                    <TableRow>
                      {/* BP27: the multi-select column — always present once there are rows, since
                          every row now has a bulk action (enable/disable/delete). */}
                      <TableHead className="w-10">
                        <label className="flex w-fit cursor-pointer items-center p-1">
                          <input
                            type="checkbox"
                            checked={allOnPageSelected}
                            onChange={toggleAllOnPage}
                            aria-label="Select all students on this page"
                            className="size-4 rounded border-hairline text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          />
                        </label>
                      </TableHead>
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
                          <label className="flex w-fit cursor-pointer items-center p-1">
                            <input
                              type="checkbox"
                              checked={isSelected(student.id)}
                              onChange={() => toggleStudent(student.id)}
                              aria-label={`Select ${student.name}`}
                              className="size-4 rounded border-hairline text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            />
                          </label>
                        </TableCell>
                        <TableCell>
                          <Link
                            href={`/students/${student.id}`}
                            className="flex items-center gap-3 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          >
                            <StudentRowAvatar student={student} />
                            <span className="flex flex-col">
                              <span className="font-medium text-ink hover:underline">
                                <Highlight text={student.name} query={urlQ} />
                              </span>
                              {student.student_group_name ? (
                                <span className="text-body-sm text-ink-secondary">
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
                            <StatusPill tone={enrollDisplay(student).tone}>
                              {enrollDisplay(student).label}
                            </StatusPill>
                            {student.enrollment_status === "failed" &&
                            student.enrollment_failure_reason ? (
                              <span className="text-body-sm text-ink-secondary">
                                {ENROLL_FAILURE_SHORT[student.enrollment_failure_reason]}
                              </span>
                            ) : null}
                            {/* BP18d: a disabled login is a distinct axis from enrollment —
                                surface it (labelled "Login disabled" so it never reads as an
                                enrollment state) so staff can spot a locked-out student at a glance. */}
                            {student.status === "disabled" ? (
                              <StatusPill tone="neutral">Login disabled</StatusPill>
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

      <ConfirmDialog
        open={deleteConfirm}
        onOpenChange={setDeleteConfirm}
        title={`Delete ${selectedCount} ${selectedCount === 1 ? "student" : "students"}?`}
        description="Permanently deletes each student's login, profile, face enrollment, and their matched-photo history — this can't be undone. The event photos themselves stay in every gallery, and past download records are kept but anonymized."
        confirmLabel={`Delete ${selectedCount} ${selectedCount === 1 ? "student" : "students"}`}
        destructive
        loading={bulkAction === "delete"}
        onConfirm={deleteBulk}
      />

      <InviteResultDialog invite={invite} onClose={() => setInvite(null)} />

      {/* BP27b: the shown-once temp passwords from a bulk resend-invite. */}
      <BulkCredentialsDialog
        title="New temporary passwords"
        description="Share each password securely — they won't be shown again. Students set their own on first sign-in."
        results={bulkCreds}
        onClose={() => setBulkCreds(null)}
      />
    </div>
  );
}

/** URL-backed filters (BP25) need a Suspense boundary (useSearchParams on a static route). */
export default function StudentsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-24 w-full" />}>
      <StudentsContent />
    </Suspense>
  );
}
