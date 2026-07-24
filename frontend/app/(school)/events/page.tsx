"use client";

import { CalendarDays, Plus } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useState } from "react";

import { type ChipItem, FilterChips } from "@/components/gallery/filter-chips";
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
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { createEvent } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { EventStatus, SortDir } from "@/lib/api/types";
import {
  EVENT_STATUS_LABEL,
  EVENT_STATUS_TONE,
  PROCESSING_LABEL,
  PROCESSING_TONE,
} from "@/lib/events/status";
import { useDashboard } from "@/lib/hooks/use-dashboard";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { useEvents } from "@/lib/hooks/use-events";
import { useListSort } from "@/lib/hooks/use-sort";
import { formatDate } from "@/lib/utils";

// Default direction when a column is first selected (BP9): names A→Z, dates newest-first,
// counts most-first. Clicking an active column toggles.
const SORT_DEFAULT_DIR: Record<string, SortDir> = {
  name: "asc",
  event_date: "desc",
  media_count: "desc",
  matched_students: "desc",
};

function CreateEventDialog({ onCreated }: { onCreated: () => void }) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [eventDate, setEventDate] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      setName("");
      setDescription("");
      setEventDate("");
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    try {
      const created = await createEvent(name.trim(), description.trim() || null, eventDate || null);
      toast(`Event “${created.name}” created.`, "success");
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
          New event
        </Button>
      </DialogTrigger>
      <DialogContent title="Create event" description="Upload photos to it, then run distribution.">
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <Field label="Name" htmlFor="event-name">
            <Input
              id="event-name"
              required
              autoFocus
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label="Description" htmlFor="event-description" hint="Optional.">
            <Textarea
              id="event-description"
              maxLength={2000}
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <Field label="Date" htmlFor="event-date" hint="Optional.">
            <Input
              id="event-date"
              type="date"
              value={eventDate}
              onChange={(e) => setEventDate(e.target.value)}
            />
          </Field>
          <div className="mt-2 flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="secondary">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" loading={submitting}>
              Create event
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function EventsPage() {
  const [rawQuery, setRawQuery] = useState("");
  const query = useDebouncedValue(rawQuery.trim(), 300);
  const [filter, setFilter] = useState<"all" | EventStatus>("all");
  const { sort, dir, onSort } = useListSort("event_date", SORT_DEFAULT_DIR);

  const { dashboard } = useDashboard();
  const { items, total, isLoading, isLoadingMore, error, reachedEnd, loadMore, mutate } =
    useEvents({ q: query || undefined, sort, dir, status: filter });

  const counts = dashboard?.events;
  const chips: ChipItem[] = [
    { id: "all", label: "All", count: counts?.total },
    { id: "active", label: "Active", count: counts?.active },
    { id: "archived", label: "Archived", count: counts?.archived },
  ];

  const isInitialLoading = isLoading && items.length === 0;
  const isFiltering = filter !== "all" || query.length > 0;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Events"
        description="Upload event photos and distribute them to the students who appear."
        actions={<CreateEventDialog onCreated={() => mutate()} />}
      />

      {isInitialLoading ? (
        <Card className="flex flex-col gap-2 p-4">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-11 w-full" />
          ))}
        </Card>
      ) : error ? (
        <EmptyState
          role="alert"
          title="Couldn't load events"
          description="Something went wrong reaching the server."
          action={
            <Button variant="secondary" onClick={() => mutate()}>
              Retry
            </Button>
          }
        />
      ) : total === 0 && !isFiltering ? (
        <EmptyState
          icon={<CalendarDays className="size-8" aria-hidden="true" />}
          title="No events yet"
          description="Create an event, upload its photos, and run distribution."
          action={<CreateEventDialog onCreated={() => mutate()} />}
        />
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <FilterChips
              items={chips}
              activeId={filter}
              onSelect={(id) => setFilter(id as "all" | EventStatus)}
              ariaLabel="Filter by event status"
            />
            <SearchInput value={rawQuery} onChange={setRawQuery} placeholder="Search events…" />
          </div>
          {total === 0 ? (
            <EmptyState title="No matching events" description="Try a different search or filter." />
          ) : (
            <>
              <Card className="overflow-hidden">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <SortableHead label="Name" sortKey="name" activeKey={sort} dir={dir} onSort={onSort} />
                      <SortableHead label="Date" sortKey="event_date" activeKey={sort} dir={dir} onSort={onSort} />
                      <SortableHead label="Photos" sortKey="media_count" activeKey={sort} dir={dir} onSort={onSort} />
                      <SortableHead label="Matched" sortKey="matched_students" activeKey={sort} dir={dir} onSort={onSort} />
                      <TableHead>Processing</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((event) => (
                      <TableRow key={event.id} className="transition-colors hover:bg-surface">
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <Link
                              href={`/events/${event.id}`}
                              className="rounded font-medium text-accent-hover hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            >
                              {event.name}
                            </Link>
                            {event.status === "archived" ? (
                              <StatusPill tone={EVENT_STATUS_TONE.archived}>
                                {EVENT_STATUS_LABEL.archived}
                              </StatusPill>
                            ) : null}
                          </div>
                        </TableCell>
                        <TableCell className="text-ink-secondary">
                          {event.event_date ? formatDate(event.event_date) : "—"}
                        </TableCell>
                        <TableCell className="tabular-nums text-ink-secondary">
                          {event.media_count}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <span className="tabular-nums text-ink-secondary">
                              {event.matched_students}
                            </span>
                            {event.needs_review > 0 ? (
                              <StatusPill tone="warning">{event.needs_review} to review</StatusPill>
                            ) : null}
                          </div>
                        </TableCell>
                        <TableCell>
                          <StatusPill tone={PROCESSING_TONE[event.processing_status]}>
                            {PROCESSING_LABEL[event.processing_status]}
                          </StatusPill>
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
    </div>
  );
}
