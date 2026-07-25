"use client";

import { BookOpen, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useState } from "react";

import { RoleGate } from "@/components/role-gate";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { createClass, deleteClass, updateClass } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { ClassListItem } from "@/lib/api/types";
import { useClasses } from "@/lib/hooks/use-classes";

/** Create or edit a class (BP11a). One form for both — `existing` pre-fills it for a rename. */
function ClassFormDialog({
  existing,
  trigger,
  onSaved,
}: {
  existing?: ClassListItem;
  trigger: React.ReactNode;
  onSaved: () => void;
}) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(existing?.name ?? "");
  const [grade, setGrade] = useState(existing?.grade ?? "");
  const [section, setSection] = useState(existing?.section ?? "");
  const [submitting, setSubmitting] = useState(false);
  const editing = existing !== undefined;

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      // Reset to the source of truth (the existing class, or blank for create).
      setName(existing?.name ?? "");
      setGrade(existing?.grade ?? "");
      setSection(existing?.section ?? "");
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    try {
      const g = grade.trim() || null;
      const s = section.trim() || null;
      if (editing) {
        await updateClass(existing.id, { name: name.trim(), grade: g, section: s });
        toast("Class updated.", "success");
      } else {
        await createClass(name.trim(), g, s);
        toast("Class created.", "success");
      }
      onSaved();
      handleOpenChange(false);
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent
        title={editing ? "Edit class" : "Create class"}
        description="Group students by class or section to filter, organize, and (soon) delegate."
      >
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <Field label="Name" htmlFor="class-name" hint="e.g. Grade 3B">
            <Input
              id="class-name"
              required
              autoFocus
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Grade" htmlFor="class-grade" hint="Optional">
              <Input
                id="class-grade"
                maxLength={50}
                value={grade}
                onChange={(e) => setGrade(e.target.value)}
              />
            </Field>
            <Field label="Section" htmlFor="class-section" hint="Optional">
              <Input
                id="class-section"
                maxLength={50}
                value={section}
                onChange={(e) => setSection(e.target.value)}
              />
            </Field>
          </div>
          <div className="mt-2 flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="secondary">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" loading={submitting}>
              {editing ? "Save changes" : "Create class"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** One class row: link to its roster + edit + delete (delete un-assigns its students). */
function ClassRow({ cls, onChanged }: { cls: ClassListItem; onChanged: () => void }) {
  const { toast } = useToast();
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const label = [cls.grade, cls.section].filter(Boolean).join(" · ") || "—";

  async function onDelete() {
    setDeleting(true);
    try {
      await deleteClass(cls.id);
      toast("Class deleted.", "success");
      onChanged();
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
      setDeleting(false);
      setConfirming(false);
    }
  }

  return (
    <TableRow className="transition-colors hover:bg-surface">
      <TableCell>
        <Link
          href={`/classes/${cls.id}`}
          className="font-medium text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {cls.name}
        </Link>
      </TableCell>
      <TableCell className="text-ink-secondary">{label}</TableCell>
      <TableCell className="text-ink-secondary tabular-nums">
        {cls.student_count} student{cls.student_count === 1 ? "" : "s"}
      </TableCell>
      <TableCell>
        <div className="flex justify-end gap-1">
          <ClassFormDialog
            // Remount (re-seed the form state) when the class's fields change, so reopening the
            // edit dialog after a rename shows the fresh values, not the first-mount ones.
            key={`${cls.name}|${cls.grade ?? ""}|${cls.section ?? ""}`}
            existing={cls}
            onSaved={onChanged}
            trigger={
              <Button variant="ghost" size="sm" aria-label={`Edit ${cls.name}`}>
                <Pencil className="size-4" aria-hidden="true" />
              </Button>
            }
          />
          <Button
            variant="ghost"
            size="sm"
            aria-label={`Delete ${cls.name}`}
            onClick={() => setConfirming(true)}
          >
            <Trash2 className="size-4 text-error" aria-hidden="true" />
          </Button>
        </div>
        <ConfirmDialog
          open={confirming}
          onOpenChange={setConfirming}
          title={`Delete ${cls.name}?`}
          description="Students in this class are un-assigned (not deleted). This can't be undone."
          confirmLabel="Delete class"
          destructive
          loading={deleting}
          onConfirm={onDelete}
        />
      </TableCell>
    </TableRow>
  );
}

function ClassesInner() {
  const { classes, isLoading, error, mutate } = useClasses();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Classes"
        description="Organize students into classes and sections."
        actions={
          <ClassFormDialog
            onSaved={() => mutate()}
            trigger={
              <Button>
                <Plus className="size-4" aria-hidden="true" />
                New class
              </Button>
            }
          />
        }
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
          title="Couldn't load classes"
          description="Something went wrong reaching the server."
          action={
            <Button variant="secondary" onClick={() => mutate()}>
              Retry
            </Button>
          }
        />
      ) : classes.length === 0 ? (
        <EmptyState
          icon={<BookOpen className="size-8" aria-hidden="true" />}
          title="No classes yet"
          description="Create a class, then assign students to it from the class page or a student's profile."
          action={
            <ClassFormDialog
              onSaved={() => mutate()}
              trigger={<Button>Create class</Button>}
            />
          }
        />
      ) : (
        <Card className="overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Class</TableHead>
                <TableHead>Grade · Section</TableHead>
                <TableHead>Students</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {classes.map((cls) => (
                <ClassRow key={cls.id} cls={cls} onChanged={() => mutate()} />
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  );
}

export default function ClassesPage() {
  // Class lifecycle is school-admin only (class:manage); teachers use the class filter on
  // the students list. A teacher who deep-links here is redirected home.
  return (
    <RoleGate allow={["school_admin"]}>
      <ClassesInner />
    </RoleGate>
  );
}
