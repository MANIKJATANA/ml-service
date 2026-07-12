"use client";

import { UserPlus } from "lucide-react";
import { useParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { useToast } from "@/components/ui/toast";
import { createSchoolAdmin } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import { useSchool } from "@/lib/hooks/use-schools";
import { formatDate } from "@/lib/utils";

function AddAdminDialog({ schoolId }: { schoolId: string }) {
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
      const admin = await createSchoolAdmin(schoolId, email.trim(), password);
      // There is no "list a school's admins" endpoint, so nothing to revalidate —
      // the toast is the confirmation (decisions/0032).
      toast(`Administrator ${admin.email} added.`, "success");
      handleOpenChange(false);
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
        description="They sign in with this temporary password and are prompted to change it on first login."
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
          <Field label="Temporary password" htmlFor="admin-password" hint="At least 8 characters.">
            <Input
              id="admin-password"
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
              Add administrator
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function SchoolDetailPage() {
  const { schoolId } = useParams<{ schoolId: string }>();
  const { school, isLoading, error, mutate } = useSchool(schoolId);

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
          <PageHeader title={school.name} actions={<AddAdminDialog schoolId={school.id} />} />
          <Card className="p-6">
            <dl className="grid gap-6 sm:grid-cols-3">
              <div className="flex flex-col gap-1">
                <dt className="text-body-sm text-ink-muted">Status</dt>
                <dd>
                  <StatusPill tone={school.status === "active" ? "success" : "warning"}>
                    {school.status}
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
          <p className="text-body-sm text-ink-muted">
            Administrators you add sign in and manage this school&apos;s staff, students, and events.
          </p>
        </>
      )}
    </div>
  );
}
