"use client";

import { Ban, Pencil, Play, UserPlus } from "lucide-react";
import { useParams } from "next/navigation";
import { type FormEvent, useState } from "react";
import { useSWRConfig } from "swr";

import { type Invite, InviteResultDialog } from "@/components/staff/invite-result-dialog";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { LoadMore } from "@/components/ui/load-more";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { StatCard } from "@/components/ui/stat-card";
import { StatusPill } from "@/components/ui/status-pill";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import {
  createSchoolAdmin,
  resendSchoolAdminInvite,
  setSchoolAdminStatus,
  updateSchool,
} from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { SchoolStatus, SchoolWithRollup, UserResponse } from "@/lib/api/types";
import { useSchool, useSchoolAdmins } from "@/lib/hooks/use-schools";
import { formatDate } from "@/lib/utils";

function adminStatus(user: UserResponse): {
  tone: "success" | "warning" | "neutral";
  label: string;
} {
  if (user.status === "disabled") return { tone: "neutral", label: "Disabled" };
  if (user.must_change_password) return { tone: "warning", label: "Awaiting sign-in" };
  return { tone: "success", label: "Active" };
}

function AddAdminDialog({
  schoolId,
  onAdded,
  onInvited,
}: {
  schoolId: string;
  onAdded: () => void;
  onInvited: (invite: Invite) => void;
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
      const { user, temp_password } = await createSchoolAdmin(schoolId, email.trim());
      toast(`Administrator ${user.email} added.`, "success");
      onAdded(); // revalidate the roster (BP2 added the list endpoint)
      handleOpenChange(false);
      onInvited({ email: user.email, tempPassword: temp_password });
    } catch (err) {
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
          Add administrator
        </Button>
      </DialogTrigger>
      <DialogContent
        title="Add administrator"
        description="We generate a temporary password for them to sign in with — you'll see it once, right after adding them."
      >
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <Field label="Email" htmlFor="admin-email">
            <Input
              id="admin-email"
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
              Add administrator
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Rename a school or change its teacher cap (BP18c). Prefilled from the current school;
 *  re-prefills on open (the record may have changed since mount). */
function EditSchoolDialog({
  school,
  onSaved,
}: {
  school: SchoolWithRollup;
  onSaved: () => void;
}) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(school.name);
  const [maxTeachers, setMaxTeachers] = useState(String(school.max_teachers));
  const [submitting, setSubmitting] = useState(false);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (next) {
      setName(school.name);
      setMaxTeachers(String(school.max_teachers));
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const count = Number.parseInt(maxTeachers, 10);
    if (!Number.isInteger(count) || count < 1 || count > 100000) {
      toast("Max teachers must be a whole number from 1 to 100,000.", "error");
      return;
    }
    setSubmitting(true);
    try {
      await updateSchool(school.id, { name: name.trim(), max_teachers: count });
      toast("School updated.", "success");
      onSaved();
      setOpen(false);
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="secondary">
          <Pencil className="size-4" aria-hidden="true" />
          Edit school
        </Button>
      </DialogTrigger>
      <DialogContent title="Edit school" description="Rename the school or change its teacher limit.">
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <Field label="Name" htmlFor="edit-school-name">
            <Input
              id="edit-school-name"
              required
              autoFocus
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label="Max teachers" htmlFor="edit-max-teachers" hint="Between 1 and 100,000.">
            <Input
              id="edit-max-teachers"
              type="number"
              inputMode="numeric"
              min={1}
              max={100000}
              step={1}
              required
              value={maxTeachers}
              onChange={(e) => setMaxTeachers(e.target.value)}
            />
          </Field>
          <div className="mt-2 flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="secondary">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" loading={submitting}>
              Save changes
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Suspend or reactivate a school (BP18c). Suspending blocks new student/teacher provisioning
 *  downstream, so it confirms first; reactivating is safe and immediate. */
function SchoolLifecycleButton({
  school,
  onChanged,
}: {
  school: SchoolWithRollup;
  onChanged: () => void;
}) {
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const [confirmSuspend, setConfirmSuspend] = useState(false);
  const isSuspended = school.status === "suspended";

  async function setStatus(status: SchoolStatus) {
    setBusy(true);
    try {
      await updateSchool(school.id, { status });
      toast(status === "suspended" ? "School suspended." : "School reactivated.", "success");
      onChanged();
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setBusy(false);
    }
  }

  if (isSuspended) {
    return (
      <Button variant="secondary" onClick={() => void setStatus("active")} loading={busy}>
        <Play className="size-4" aria-hidden="true" />
        Reactivate
      </Button>
    );
  }
  return (
    <>
      <Button variant="secondary" onClick={() => setConfirmSuspend(true)} loading={busy}>
        <Ban className="size-4" aria-hidden="true" />
        Suspend
      </Button>
      <ConfirmDialog
        open={confirmSuspend}
        onOpenChange={setConfirmSuspend}
        title="Suspend this school?"
        description="While suspended, staff can't add students or teachers. You can reactivate it anytime."
        confirmLabel="Suspend school"
        destructive
        onConfirm={() => {
          setConfirmSuspend(false);
          void setStatus("suspended");
        }}
      />
    </>
  );
}

/** Per-row admin lifecycle actions (BP7c): re-issue a one-time temp password, or
 *  enable/disable the account. BP18b: resending an already-signed-in admin confirms first
 *  (it replaces their password). Disabling a school's only ACTIVE admin is refused by the
 *  backend and surfaced as an error toast — a11y-friendlier than a title-only disabled button,
 *  and it also catches the "1 active + 1 disabled" case a client-side count would miss. */
function AdminActions({
  schoolId,
  admin,
  onInvited,
  onChanged,
}: {
  schoolId: string;
  admin: UserResponse;
  onInvited: (invite: Invite) => void;
  onChanged: () => Promise<unknown>;
}) {
  const { toast } = useToast();
  const [busy, setBusy] = useState<"status" | "resend" | null>(null);
  const [confirmResend, setConfirmResend] = useState(false);
  const isDisabled = admin.status === "disabled";
  // Resending nukes a working password — confirm only once they've set their own (signed in:
  // active + no pending change). An awaiting-sign-in / disabled account resends freely.
  const resendNeedsConfirm = admin.status === "active" && !admin.must_change_password;

  async function toggleStatus() {
    setBusy("status");
    try {
      await setSchoolAdminStatus(schoolId, admin.id, isDisabled ? "active" : "disabled");
      toast(isDisabled ? "Administrator enabled." : "Administrator disabled.", "success");
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
      const { user, temp_password } = await resendSchoolAdminInvite(schoolId, admin.id);
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
          aria-label={`Resend invite for ${admin.email}`}
        >
          Resend invite
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={toggleStatus}
          loading={busy === "status"}
          disabled={busy !== null}
          aria-label={`${isDisabled ? "Enable" : "Disable"} ${admin.email}`}
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

function AdminRoster({
  schoolId,
  onInvited,
}: {
  schoolId: string;
  onInvited: (invite: Invite) => void;
}) {
  const { items, total, isLoading, isLoadingMore, error, reachedEnd, loadMore, mutate } =
    useSchoolAdmins(schoolId, {});
  const isInitialLoading = isLoading && items.length === 0;

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-headline text-ink">Administrators</h2>
      {isInitialLoading ? (
        <Card className="flex flex-col gap-2 p-4">
          {[0, 1].map((i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </Card>
      ) : error ? (
        <EmptyState
          role="alert"
          title="Couldn't load administrators"
          description="Something went wrong reaching the server."
          action={
            <Button variant="secondary" onClick={() => mutate()}>
              Retry
            </Button>
          }
        />
      ) : total === 0 ? (
        <EmptyState title="No administrators yet" description="Add one to let them run this school." />
      ) : (
        <>
          <Card className="overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Email</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Added</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((admin) => {
                  const status = adminStatus(admin);
                  return (
                    <TableRow key={admin.id}>
                      <TableCell>{admin.email}</TableCell>
                      <TableCell>
                        <StatusPill tone={status.tone}>{status.label}</StatusPill>
                      </TableCell>
                      <TableCell className="text-ink-secondary">
                        {formatDate(admin.created_at)}
                      </TableCell>
                      <TableCell>
                        <AdminActions
                          schoolId={schoolId}
                          admin={admin}
                          onInvited={onInvited}
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
    </section>
  );
}

export default function SchoolDetailPage() {
  const { schoolId } = useParams<{ schoolId: string }>();
  const { school, isLoading, error, mutate } = useSchool(schoolId);
  // Revalidate the roster (owned by <AdminRoster/>) by its shared SWR key after an add.
  const { mutate: mutateKey } = useSWRConfig();
  const [invite, setInvite] = useState<Invite | null>(null);

  const notFound = isApiError(error) && error.status === 404;

  return (
    <div className="flex flex-col gap-6">
      <Breadcrumb
        items={[{ label: "Schools", href: "/schools" }, { label: school?.name ?? "School" }]}
      />

      {isLoading ? (
        <>
          <Skeleton className="h-9 w-64" />
          <Card className="flex flex-col gap-3 p-6">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-4 w-32" />
          </Card>
        </>
      ) : error || !school ? (
        <EmptyState
          role="alert"
          title={notFound ? "School not found" : "Couldn't load school"}
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
            title={school.name}
            actions={
              <div className="flex flex-wrap gap-2">
                <EditSchoolDialog school={school} onSaved={() => void mutate()} />
                <SchoolLifecycleButton school={school} onChanged={() => void mutate()} />
                <AddAdminDialog
                  schoolId={school.id}
                  onAdded={() =>
                    // The roster is now paginated (keys carry a query + page suffix), so
                    // revalidate every page of it with a key-prefix matcher (BP9).
                    mutateKey(
                      (key) =>
                        typeof key === "string" &&
                        key.startsWith(`schools/${school.id}/admins`),
                    )
                  }
                  onInvited={setInvite}
                />
              </div>
            }
          />
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Administrators" value={school.rollup.admins} />
            <StatCard
              label="Teachers"
              value={school.rollup.teachers}
              hint={`of ${school.max_teachers.toLocaleString()} allowed`}
            />
            <StatCard label="Students" value={school.rollup.students} />
            <StatCard label="Events" value={school.rollup.events} />
          </div>
          <Card className="p-6">
            <dl className="grid gap-6 sm:grid-cols-3">
              <div className="flex flex-col gap-1">
                <dt className="text-body-sm text-ink-muted">Status</dt>
                <dd>
                  <StatusPill tone={school.status === "active" ? "success" : "warning"}>
                    {school.status === "active" ? "Active" : "Suspended"}
                  </StatusPill>
                </dd>
              </div>
              <div className="flex flex-col gap-1">
                <dt className="text-body-sm text-ink-muted">Max teachers</dt>
                <dd className="text-body tabular-nums text-ink">
                  {school.max_teachers.toLocaleString()}
                </dd>
              </div>
              <div className="flex flex-col gap-1">
                <dt className="text-body-sm text-ink-muted">Created</dt>
                <dd className="text-body text-ink">{formatDate(school.created_at)}</dd>
              </div>
            </dl>
          </Card>
          <AdminRoster schoolId={school.id} onInvited={setInvite} />
        </>
      )}

      <InviteResultDialog invite={invite} onClose={() => setInvite(null)} />
    </div>
  );
}
