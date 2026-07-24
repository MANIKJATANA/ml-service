"use client";

import { UserPlus, Users } from "lucide-react";
import { type FormEvent, useState } from "react";

import { RoleGate } from "@/components/role-gate";
import { type Invite, InviteResultDialog } from "@/components/staff/invite-result-dialog";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { LoadMore } from "@/components/ui/load-more";
import { PageHeader } from "@/components/ui/page-header";
import { SearchInput } from "@/components/ui/search-input";
import { Skeleton } from "@/components/ui/skeleton";
import { SortableHead } from "@/components/ui/sortable-head";
import { StatusPill } from "@/components/ui/status-pill";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { createStaff, resendStaffInvite, setStaffStatus } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { SortDir, UserResponse } from "@/lib/api/types";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { useListSort } from "@/lib/hooks/use-sort";
import { useStaff } from "@/lib/hooks/use-staff";
import { formatDate } from "@/lib/utils";

// Default direction when a column is first selected (BP9): email A→Z, added newest-first.
const SORT_DEFAULT_DIR: Record<string, SortDir> = {
  email: "asc",
  created_at: "desc",
};

function staffStatus(user: UserResponse): {
  tone: "success" | "warning" | "neutral";
  label: string;
} {
  if (user.status === "disabled") return { tone: "neutral", label: "Disabled" };
  if (user.must_change_password) return { tone: "warning", label: "Awaiting sign-in" };
  return { tone: "success", label: "Active" };
}

function CreateTeacherDialog({ onInvited }: { onInvited: (invite: Invite) => void }) {
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
 *  the account (a disabled teacher can't sign in). */
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
  const isDisabled = teacher.status === "disabled";

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

  return (
    <div className="flex justify-end gap-1">
      <Button
        variant="ghost"
        size="sm"
        onClick={resend}
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
  );
}

function StaffContent() {
  const [rawQuery, setRawQuery] = useState("");
  const query = useDebouncedValue(rawQuery.trim(), 300);
  const { sort, dir, onSort } = useListSort("email", SORT_DEFAULT_DIR);
  const [invite, setInvite] = useState<Invite | null>(null);

  const { items, total, isLoading, isLoadingMore, error, reachedEnd, loadMore, mutate } =
    useStaff({ q: query || undefined, sort, dir });

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
        actions={<CreateTeacherDialog onInvited={setInvite} />}
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
      ) : total === 0 && query.length === 0 ? (
        <EmptyState
          icon={<Users className="size-8" aria-hidden="true" />}
          title="No teachers yet"
          description="Add a teacher to help manage this school."
          action={<CreateTeacherDialog onInvited={setInvite} />}
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
                      <SortableHead label="Added" sortKey="created_at" activeKey={sort} dir={dir} onSort={onSort} />
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((teacher) => {
                      const status = staffStatus(teacher);
                      return (
                        <TableRow key={teacher.id}>
                          <TableCell>{teacher.email}</TableCell>
                          <TableCell>
                            <StatusPill tone={status.tone}>{status.label}</StatusPill>
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
      <StaffContent />
    </RoleGate>
  );
}
