"use client";

import { UserPlus, Users } from "lucide-react";
import { type FormEvent, useState } from "react";

import { RoleGate } from "@/components/role-gate";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { createStaff } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { UserResponse } from "@/lib/api/types";
import { useStaff } from "@/lib/hooks/use-staff";

function staffStatus(user: UserResponse): {
  tone: "success" | "warning" | "neutral";
  label: string;
} {
  if (user.status === "disabled") return { tone: "neutral", label: "Disabled" };
  if (user.must_change_password) return { tone: "warning", label: "Awaiting sign-in" };
  return { tone: "success", label: "Active" };
}

function CreateTeacherDialog({ onCreated }: { onCreated: () => void }) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      setEmail("");
      setPassword("");
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    try {
      const teacher = await createStaff(email.trim(), password);
      toast(`Teacher ${teacher.email} added.`, "success");
      onCreated();
      handleOpenChange(false);
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
        description="They sign in with this temporary password and change it on first login."
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
          <Field label="Temporary password" htmlFor="teacher-password" hint="At least 8 characters.">
            <Input
              id="teacher-password"
              type="text"
              autoComplete="off"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
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

function StaffContent() {
  const { staff, isLoading, error, mutate } = useStaff();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Staff"
        description="Teachers who manage students, events, and galleries."
        actions={<CreateTeacherDialog onCreated={() => mutate()} />}
      />

      {isLoading ? (
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
      ) : !staff || staff.length === 0 ? (
        <EmptyState
          icon={<Users className="size-8" aria-hidden="true" />}
          title="No teachers yet"
          description="Add a teacher to help manage this school."
          action={<CreateTeacherDialog onCreated={() => mutate()} />}
        />
      ) : (
        <Card className="overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {staff.map((teacher) => {
                const status = staffStatus(teacher);
                return (
                  <TableRow key={teacher.id}>
                    <TableCell>{teacher.email}</TableCell>
                    <TableCell>
                      <StatusPill tone={status.tone}>{status.label}</StatusPill>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </Card>
      )}
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
