"use client";

import { Building2, Plus } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useState } from "react";

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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { createSchool } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { SchoolStatus, SortDir } from "@/lib/api/types";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { useSchools } from "@/lib/hooks/use-schools";
import { useListSort } from "@/lib/hooks/use-sort";

const STATUS_TONE: Record<SchoolStatus, "success" | "warning"> = {
  active: "success",
  suspended: "warning",
};

// Default direction when a column is first selected (BP9): name A→Z, counts most-first.
const SORT_DEFAULT_DIR: Record<string, SortDir> = {
  name: "asc",
  students: "desc",
  events: "desc",
};

function CreateSchoolDialog({ onCreated }: { onCreated: () => void }) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [maxTeachers, setMaxTeachers] = useState("10");
  const [submitting, setSubmitting] = useState(false);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      setName("");
      setMaxTeachers("10");
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
      await createSchool(name.trim(), count);
      toast("School created.", "success");
      onCreated();
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
          <Plus className="size-4" aria-hidden="true" />
          New school
        </Button>
      </DialogTrigger>
      <DialogContent title="Create school" description="Add a school and set its teacher limit.">
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <Field label="Name" htmlFor="school-name">
            <Input
              id="school-name"
              required
              autoFocus
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label="Max teachers" htmlFor="max-teachers" hint="Between 1 and 100,000.">
            <Input
              id="max-teachers"
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
              Create
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function SchoolsPage() {
  const [rawQuery, setRawQuery] = useState("");
  const query = useDebouncedValue(rawQuery.trim(), 300);
  const { sort, dir, onSort } = useListSort("name", SORT_DEFAULT_DIR);

  const { items, total, isLoading, isLoadingMore, error, reachedEnd, loadMore, mutate } =
    useSchools({ q: query || undefined, sort, dir });

  const isInitialLoading = isLoading && items.length === 0;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Schools"
        description="Onboard schools and provision their administrators."
        actions={<CreateSchoolDialog onCreated={() => mutate()} />}
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
          title="Couldn't load schools"
          description="Something went wrong reaching the server."
          action={
            <Button variant="secondary" onClick={() => mutate()}>
              Retry
            </Button>
          }
        />
      ) : total === 0 && query.length === 0 ? (
        <EmptyState
          icon={<Building2 className="size-8" aria-hidden="true" />}
          title="No schools yet"
          description="Create your first school to get started."
          action={<CreateSchoolDialog onCreated={() => mutate()} />}
        />
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex justify-end">
            <SearchInput value={rawQuery} onChange={setRawQuery} placeholder="Search schools…" />
          </div>
          {total === 0 ? (
            <EmptyState title="No matching schools" description="Try a different search." />
          ) : (
            <>
              <Card className="overflow-hidden">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <SortableHead label="Name" sortKey="name" activeKey={sort} dir={dir} onSort={onSort} />
                      <TableHead>Admins</TableHead>
                      <TableHead>Teachers</TableHead>
                      <SortableHead label="Students" sortKey="students" activeKey={sort} dir={dir} onSort={onSort} />
                      <SortableHead label="Events" sortKey="events" activeKey={sort} dir={dir} onSort={onSort} />
                      <TableHead>Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((school) => {
                      const atCap = school.rollup.teachers >= school.max_teachers;
                      return (
                        <TableRow key={school.id} className="transition-colors hover:bg-surface">
                          <TableCell>
                            <Link
                              href={`/schools/${school.id}`}
                              className="rounded font-medium text-accent-hover hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            >
                              {school.name}
                            </Link>
                          </TableCell>
                          <TableCell className="tabular-nums text-ink-secondary">
                            {school.rollup.admins}
                          </TableCell>
                          <TableCell>
                            <span
                              className={cnCap(atCap)}
                              title={atCap ? "Teacher limit reached" : undefined}
                            >
                              {school.rollup.teachers} / {school.max_teachers.toLocaleString()}
                            </span>
                          </TableCell>
                          <TableCell className="tabular-nums text-ink-secondary">
                            {school.rollup.students}
                          </TableCell>
                          <TableCell className="tabular-nums text-ink-secondary">
                            {school.rollup.events}
                          </TableCell>
                          <TableCell>
                            <StatusPill tone={STATUS_TONE[school.status]}>
                              {school.status === "active" ? "Active" : "Suspended"}
                            </StatusPill>
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
    </div>
  );
}

function cnCap(atCap: boolean): string {
  return atCap
    ? "tabular-nums font-medium text-warning-strong"
    : "tabular-nums text-ink-secondary";
}
