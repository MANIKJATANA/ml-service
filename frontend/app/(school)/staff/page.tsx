"use client";

import { UserPlus, Users } from "lucide-react";
import { type FormEvent, Suspense, useEffect, useState } from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { RoleGate } from "@/components/role-gate";
import { type Invite, InviteResultDialog } from "@/components/staff/invite-result-dialog";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { Highlight } from "@/components/ui/highlight";
import { Input } from "@/components/ui/input";
import { LoadMore } from "@/components/ui/load-more";
import { PageHeader } from "@/components/ui/page-header";
import { SearchInput } from "@/components/ui/search-input";
import { Skeleton } from "@/components/ui/skeleton";
import { SortableHead } from "@/components/ui/sortable-head";
import { StatusPill } from "@/components/ui/status-pill";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import {
  createStaff,
  getTeacherClasses,
  resendStaffInvite,
  setStaffStatus,
  setTeacherClasses,
} from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { ClassResponse, SortDir, UserResponse } from "@/lib/api/types";
import { useClasses } from "@/lib/hooks/use-classes";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { useUrlListSort } from "@/lib/hooks/use-sort";
import { useStaff } from "@/lib/hooks/use-staff";
import { useUrlParams } from "@/lib/hooks/use-url-state";
import { formatDate } from "@/lib/utils";

// Default direction when a column is first selected (BP9): email A→Z, added + last-sign-in
// newest-first (BP23).
const SORT_DEFAULT_DIR: Record<string, SortDir> = {
  email: "asc",
  created_at: "desc",
  last_login_at: "desc",
};

function staffStatus(user: UserResponse): {
  tone: "success" | "warning" | "neutral";
  label: string;
} {
  if (user.status === "disabled") return { tone: "neutral", label: "Disabled" };
  if (user.must_change_password) return { tone: "warning", label: "Awaiting sign-in" };
  return { tone: "success", label: "Active" };
}

function CreateTeacherDialog({
  onInvited,
  onCreated,
}: {
  onInvited: (invite: Invite) => void;
  onCreated: () => void;
}) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) setEmail("");
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    try {
      const { user, temp_password } = await createStaff(email.trim());
      toast(`Teacher ${user.email} added.`, "success");
      onCreated(); // BP24 (R3-S3-01): refresh the roster so the new teacher appears at once
      handleOpenChange(false);
      onInvited({ email: user.email, tempPassword: temp_password });
    } catch (err) {
      // 409 = duplicate email OR the school's teacher cap — the detail says which.
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
          Add teacher
        </Button>
      </DialogTrigger>
      <DialogContent
        title="Add teacher"
        description="We generate a temporary password for them to sign in with — you'll see it once, right after adding them."
      >
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <Field label="Email" htmlFor="teacher-email">
            <Input
              id="teacher-email"
              type="email"
              autoComplete="off"
              required
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
          <div className="mt-2 flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="secondary">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" loading={submitting}>
              Add teacher
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Per-row lifecycle actions (BP7c): re-issue a one-time temp password, or enable/disable
 *  the account (a disabled teacher can't sign in). BP18b: resending an already-signed-in
 *  teacher confirms first — it replaces their working password. */
function StaffActions({
  teacher,
  onInvited,
  onChanged,
}: {
  teacher: UserResponse;
  onInvited: (invite: Invite) => void;
  onChanged: () => Promise<unknown>;
}) {
  const { toast } = useToast();
  const [busy, setBusy] = useState<"status" | "resend" | null>(null);
  const [confirmResend, setConfirmResend] = useState(false);
  const isDisabled = teacher.status === "disabled";
  // Resending nukes a working password — confirm only once they've set their own (signed in:
  // active + no pending change). An awaiting-sign-in / disabled account resends freely.
  const resendNeedsConfirm = teacher.status === "active" && !teacher.must_change_password;

  async function toggleStatus() {
    setBusy("status");
    try {
      await setStaffStatus(teacher.id, isDisabled ? "active" : "disabled");
      toast(isDisabled ? "Teacher enabled." : "Teacher disabled.", "success");
      await onChanged();
    } catch (err) {
      toast(isApiError(err) ? err.message : "Couldn't update. Please try again.", "error");
    } finally {
      setBusy(null);
    }
  }

  async function resend() {
    setBusy("resend");
    try {
      const { user, temp_password } = await resendStaffInvite(teacher.id);
      onInvited({ email: user.email, tempPassword: temp_password });
      await onChanged(); // must_change_password flips back -> refresh the status pill
    } catch (err) {
      toast(isApiError(err) ? err.message : "Couldn't resend. Please try again.", "error");
    } finally {
      setBusy(null);
    }
  }

  function onResendClick() {
    if (resendNeedsConfirm) setConfirmResend(true);
    else void resend();
  }

  return (
    <>
      <div className="flex justify-end gap-1">
        <Button
          variant="ghost"
          size="sm"
          onClick={onResendClick}
          loading={busy === "resend"}
          disabled={busy !== null}
          aria-label={`Resend invite for ${teacher.email}`}
        >
          Resend invite
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={toggleStatus}
          loading={busy === "status"}
          disabled={busy !== null}
          aria-label={`${isDisabled ? "Enable" : "Disable"} ${teacher.email}`}
        >
          {isDisabled ? "Enable" : "Disable"}
        </Button>
      </div>
      <ConfirmDialog
        open={confirmResend}
        onOpenChange={setConfirmResend}
        title="Send a new password?"
        description="This replaces their current password — they'll have to sign in with the new one and set their own again."
        confirmLabel="Send new password"
        onConfirm={() => {
          setConfirmResend(false);
          void resend();
        }}
      />
    </>
  );
}

/** Set a teacher's whole class set (BP11c) — a checkbox list of the school's classes, initialized
 *  from the teacher's current assignments, PUT as one set. */
function EditClassesDialog({
  teacher,
  assigned,
  onSaved,
}: {
  teacher: UserResponse;
  assigned: ClassResponse[];
  onSaved: () => void;
}) {
  const { toast } = useToast();
  const { classes } = useClasses();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (next) setSelected(new Set(assigned.map((c) => c.id)));
  }

  function toggle(id: string) {
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function onSave() {
    setSaving(true);
    try {
      await setTeacherClasses(teacher.id, [...selected]);
      toast("Classes updated.", "success");
      onSaved();
      // Also refresh any open class-detail teacher rosters (a different SWR namespace).
      void globalMutate((k) => typeof k === "string" && k.startsWith("class-teachers:"));
      setOpen(false);
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" aria-label={`Edit classes for ${teacher.email}`}>
          Edit classes
        </Button>
      </DialogTrigger>
      <DialogContent
        title="Edit classes"
        description={`Which classes does ${teacher.email} manage? They'll see those students and events focused first.`}
      >
        <div className="flex flex-col gap-3">
          {classes.length === 0 ? (
            <p className="text-body-sm text-ink-secondary">
              No classes yet. Create classes first, then assign them here.
            </p>
          ) : (
            <ul className="max-h-64 divide-y divide-hairline overflow-y-auto overscroll-contain rounded-button border border-hairline">
              {classes.map((c) => (
                <li key={c.id}>
                  <label className="flex cursor-pointer items-center gap-2 px-3 py-2 hover:bg-surface">
                    <input
                      type="checkbox"
                      checked={selected.has(c.id)}
                      onChange={() => toggle(c.id)}
                      className="size-4 rounded border-hairline text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    />
                    <span className="min-w-0 flex-1 truncate text-body-sm text-ink">{c.name}</span>
                    {(c.grade || c.section) && (
                      <span className="shrink-0 text-body-sm text-ink-secondary">
                        {[c.grade, c.section].filter(Boolean).join(" · ")}
                      </span>
                    )}
                  </label>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-1 flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="secondary">
                Cancel
              </Button>
            </DialogClose>
            <Button onClick={onSave} loading={saving} disabled={classes.length === 0}>
              Save
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** The teacher's assigned classes (BP11c) — a name summary + the Edit dialog. Per-row SWR keyed
 *  on the teacher; the staff roster is bounded, so N small fetches are fine. */
function ClassesCell({ teacher }: { teacher: UserResponse }) {
  const { data, mutate } = useSWR(`staff-classes:${teacher.id}`, () =>
    getTeacherClasses(teacher.id),
  );
  const assigned = data?.items ?? [];
  return (
    <div className="flex items-center gap-2">
      <span className="min-w-0 truncate text-ink-secondary" title={assigned.map((c) => c.name).join(", ")}>
        {assigned.length > 0 ? assigned.map((c) => c.name).join(", ") : "—"}
      </span>
      <EditClassesDialog teacher={teacher} assigned={assigned} onSaved={() => void mutate()} />
    </div>
  );
}

function StaffContent() {
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
  const { sort, dir, onSort } = useUrlListSort("email", SORT_DEFAULT_DIR, { get, set });
  const [invite, setInvite] = useState<Invite | null>(null);

  const { items, total, isLoading, isLoadingMore, error, reachedEnd, loadMore, mutate } =
    useStaff({ q: urlQ || undefined, sort, dir });

  const isInitialLoading = isLoading && items.length === 0;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Staff"
        description={
          total > 0
            ? `${total} ${total === 1 ? "teacher" : "teachers"} managing students, events, and galleries.`
            : "Teachers who manage students, events, and galleries."
        }
        actions={<CreateTeacherDialog onInvited={setInvite} onCreated={() => mutate()} />}
      />

      {isInitialLoading ? (
        <Card className="flex flex-col gap-2 p-4">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </Card>
      ) : error ? (
        <EmptyState
          role="alert"
          title="Couldn't load staff"
          description="Something went wrong reaching the server."
          action={
            <Button variant="secondary" onClick={() => mutate()}>
              Retry
            </Button>
          }
        />
      ) : total === 0 && urlQ.length === 0 ? (
        <EmptyState
          icon={<Users className="size-8" aria-hidden="true" />}
          title="No teachers yet"
          description="Add a teacher to help manage this school."
          action={<CreateTeacherDialog onInvited={setInvite} onCreated={() => mutate()} />}
        />
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex justify-end">
            <SearchInput value={rawQuery} onChange={setRawQuery} placeholder="Search by email…" />
          </div>
          {total === 0 ? (
            <EmptyState title="No matching teachers" description="Try a different search." />
          ) : (
            <>
              <Card className="overflow-hidden">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <SortableHead label="Email" sortKey="email" activeKey={sort} dir={dir} onSort={onSort} />
                      <TableHead>Status</TableHead>
                      <TableHead>Classes</TableHead>
                      <SortableHead label="Last sign-in" sortKey="last_login_at" activeKey={sort} dir={dir} onSort={onSort} />
                      <SortableHead label="Added" sortKey="created_at" activeKey={sort} dir={dir} onSort={onSort} />
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((teacher) => {
                      const status = staffStatus(teacher);
                      return (
                        <TableRow key={teacher.id}>
                          <TableCell>
                            <Highlight text={teacher.email} query={urlQ} />
                          </TableCell>
                          <TableCell>
                            <StatusPill tone={status.tone}>{status.label}</StatusPill>
                          </TableCell>
                          <TableCell className="max-w-[16rem]">
                            <ClassesCell teacher={teacher} />
                          </TableCell>
                          <TableCell className="text-ink-secondary">
                            {teacher.last_login_at ? formatDate(teacher.last_login_at) : "Never"}
                          </TableCell>
                          <TableCell className="text-ink-secondary">
                            {formatDate(teacher.created_at)}
                          </TableCell>
                          <TableCell>
                            <StaffActions
                              teacher={teacher}
                              onInvited={setInvite}
                              onChanged={() => mutate()}
                            />
                          </TableCell>
                        </TableRow>
                      );
                    })}
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

// Staff management is school-admin-only (teachers lack `staff:manage`); the nav
// already hides it from teachers — this guards a direct URL hit (decisions/0033).
export default function StaffPage() {
  return (
    <RoleGate allow={["school_admin"]}>
      {/* URL-backed filters (BP25) need a Suspense boundary (useSearchParams, static route). */}
      <Suspense fallback={<Skeleton className="h-24 w-full" />}>
        <StaffContent />
      </Suspense>
    </RoleGate>
  );
}
