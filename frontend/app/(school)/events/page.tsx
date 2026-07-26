"use client";

import { CalendarDays, Plus } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useState } from "react";
import { mutate as globalMutate } from "swr";

import { FocusToggle } from "@/components/delegation/focus-toggle";
import { ManageCategoriesDialog } from "@/components/events/manage-categories-dialog";
import { MonthCalendar } from "@/components/events/month-calendar";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { bulkEventStatus, createEvent } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { EventStatus, SortDir } from "@/lib/api/types";
import { buildMonthGrid, currentMonth, shiftMonth } from "@/lib/events/calendar";
import { categoryColor } from "@/lib/events/categories";
import {
  EVENT_STATUS_LABEL,
  EVENT_STATUS_TONE,
  PROCESSING_LABEL,
  PROCESSING_TONE,
} from "@/lib/events/status";
import { useClasses } from "@/lib/hooks/use-classes";
import { useDashboard } from "@/lib/hooks/use-dashboard";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { useEventCategories, useEventTerms } from "@/lib/hooks/use-event-categories";
import { useEvents } from "@/lib/hooks/use-events";
import { useMe } from "@/lib/hooks/use-me";
import { useMyClasses } from "@/lib/hooks/use-my-classes";
import { useListSort } from "@/lib/hooks/use-sort";
import { useMonthEvents } from "@/lib/hooks/use-month-events";
import { cn, formatDate } from "@/lib/utils";

const SORT_DEFAULT_DIR: Record<string, SortDir> = {
  name: "asc",
  event_date: "desc",
  media_count: "desc",
  matched_students: "desc",
};

const SELECT_CLASS =
  "h-10 rounded-button border border-hairline bg-canvas px-3 text-body text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** A category badge (colored by id) or an em-dash for an uncategorized event. */
function CategoryBadge({
  categoryId,
  categoryName,
}: {
  categoryId: string | null;
  categoryName: string | null;
}) {
  if (!categoryId || !categoryName) return <span className="text-ink-muted">—</span>;
  return (
    <span
      className={cn(
        "inline-block rounded-full px-2.5 py-0.5 text-body-sm font-medium",
        categoryColor(categoryId),
      )}
    >
      {categoryName}
    </span>
  );
}

function CreateEventDialog({ onCreated }: { onCreated: () => void }) {
  const { toast } = useToast();
  const { categories } = useEventCategories();
  const { classes } = useClasses();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [eventDate, setEventDate] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [term, setTerm] = useState("");
  const [classId, setClassId] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const otherId = categories.find((c) => c.name.trim().toLowerCase() === "other")?.id ?? "";

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (next) {
      setCategoryId(otherId); // preselect "Other" when the school has it
    } else {
      setName("");
      setDescription("");
      setEventDate("");
      setCategoryId("");
      setTerm("");
      setClassId("");
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    try {
      const created = await createEvent(
        name.trim(),
        description.trim() || null,
        eventDate || null,
        categoryId || null,
        term.trim() || null,
        classId || null,
      );
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
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Date" htmlFor="event-date" hint="Optional.">
              <Input
                id="event-date"
                type="date"
                value={eventDate}
                onChange={(e) => setEventDate(e.target.value)}
              />
            </Field>
            <Field label="Category" htmlFor="event-category" hint="Optional.">
              <select
                id="event-category"
                value={categoryId}
                onChange={(e) => setCategoryId(e.target.value)}
                className={SELECT_CLASS}
              >
                <option value="">No category</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Term" htmlFor="event-term" hint="Optional, e.g. Fall 2026.">
              <Input
                id="event-term"
                maxLength={100}
                value={term}
                onChange={(e) => setTerm(e.target.value)}
              />
            </Field>
            {classes.length > 0 ? (
              <Field
                label="Class"
                htmlFor="event-class"
                hint="Optional — leave as school-wide for events everyone attends."
              >
                <select
                  id="event-class"
                  value={classId}
                  onChange={(e) => setClassId(e.target.value)}
                  className={SELECT_CLASS}
                >
                  <option value="">School-wide</option>
                  {classes.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}
          </div>
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

/** The Calendar tab (BP11b). Mounts only when the tab is active (Radix unmounts inactive
 *  content), so its month fetch only runs when viewed. Filters are shared with the List tab. */
function CalendarView({
  categoryId,
  term,
  status,
  classId,
  mine,
}: {
  categoryId: string;
  term: string;
  status: string;
  classId: string;
  mine: boolean;
}) {
  const [{ year, month }, setYm] = useState(currentMonth);
  const grid = buildMonthGrid(year, month);
  const { events, total, isLoading } = useMonthEvents(grid.gridStart, grid.gridEnd, {
    category_id: categoryId || undefined,
    term: term || undefined,
    status,
    student_group_id: classId || undefined,
    mine,
  });
  return (
    <div className="flex flex-col gap-3">
      <MonthCalendar
        grid={grid}
        events={events}
        loading={isLoading}
        onPrev={() => setYm((s) => shiftMonth(s.year, s.month, -1))}
        onNext={() => setYm((s) => shiftMonth(s.year, s.month, 1))}
        onToday={() => setYm(currentMonth())}
      />
      {total > events.length ? (
        <p className="text-body-sm text-warning-strong">
          Showing {events.length} of {total} events in this range — switch to the List tab to
          see them all.
        </p>
      ) : null}
    </div>
  );
}

export default function EventsPage() {
  const [rawQuery, setRawQuery] = useState("");
  const query = useDebouncedValue(rawQuery.trim(), 300);
  const [filter, setFilter] = useState<"all" | EventStatus>("all");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [termFilter, setTermFilter] = useState("");
  const [classFilter, setClassFilter] = useState("");
  const [focus, setFocus] = useState(true); // BP11c: default a teacher to their classes
  const { sort, dir, onSort } = useListSort("event_date", SORT_DEFAULT_DIR);
  const [tab, setTab] = useState("list");

  const { dashboard } = useDashboard();
  const { categories } = useEventCategories();
  const terms = useEventTerms();
  const { classes } = useClasses();
  const { user } = useMe();
  const isTeacher = user?.role === "teacher";
  const { classes: myClasses } = useMyClasses(isTeacher);
  const canFocus = isTeacher && myClasses.length > 0;
  const focusOn = canFocus && focus;

  // Derived so a deleted category / vanished term / removed class can't strand the list
  // (BP11a pattern).
  const activeCategory =
    categoryFilter && categories.some((c) => c.id === categoryFilter) ? categoryFilter : "";
  const activeTerm = termFilter && terms.includes(termFilter) ? termFilter : "";
  const activeClass =
    classFilter && classes.some((c) => c.id === classFilter) ? classFilter : "";

  const { items, total, isLoading, isLoadingMore, error, reachedEnd, loadMore, mutate } =
    useEvents({
      q: query || undefined,
      sort,
      dir,
      status: filter,
      category_id: activeCategory || undefined,
      term: activeTerm || undefined,
      student_group_id: activeClass || undefined,
      mine: focusOn,
    });

  const { toast } = useToast();
  // BP13 bulk archive: selection over the loaded rows. Derived (not effect-reconciled) so a
  // filter change that drops rows can't leave a stale id selected — only still-visible rows act.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const selectedIds = items.filter((e) => selected.has(e.id)).map((e) => e.id);
  const allOnPageSelected = items.length > 0 && selectedIds.length === items.length;

  function toggleAllOnPage() {
    setSelected(allOnPageSelected ? new Set() : new Set(items.map((e) => e.id)));
  }
  function toggleEvent(id: string) {
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  async function bulkSetStatus(status: EventStatus) {
    if (selectedIds.length === 0) return;
    setBulkBusy(true);
    try {
      const { updated } = await bulkEventStatus(selectedIds, status);
      toast(
        `${status === "archived" ? "Archived" : "Restored"} ${updated} ${updated === 1 ? "event" : "events"}.`,
        "success",
      );
      setSelected(new Set());
      await mutate();
      void globalMutate("dashboard");
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setBulkBusy(false);
    }
  }

  const counts = dashboard?.events;
  const chips: ChipItem[] = [
    { id: "all", label: "All", count: counts?.total },
    { id: "active", label: "Active", count: counts?.active },
    { id: "archived", label: "Archived", count: counts?.archived },
  ];

  const isInitialLoading = isLoading && items.length === 0;
  const isFiltering =
    filter !== "all" ||
    query.length > 0 ||
    activeCategory !== "" ||
    activeTerm !== "" ||
    activeClass !== "" ||
    focusOn;

  function onCreated() {
    void mutate();
    void globalMutate("event-terms"); // a new term becomes filterable
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Events"
        description="Upload event photos and distribute them to the students who appear."
        actions={
          <div className="flex flex-wrap gap-2">
            <ManageCategoriesDialog onChanged={() => mutate()} />
            <CreateEventDialog onCreated={onCreated} />
          </div>
        }
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
          action={<CreateEventDialog onCreated={onCreated} />}
        />
      ) : (
        <div className="flex flex-col gap-4">
          {/* Row 1: the primary status filter on its own line. */}
          <FilterChips
            items={chips}
            activeId={filter}
            onSelect={(id) => setFilter(id as "all" | EventStatus)}
            ariaLabel="Filter by event status"
          />
          {/* Row 2: the scope toggle + class/category/term filters (all AND together). */}
          <div className="flex flex-wrap items-center gap-2">
              {canFocus ? <FocusToggle value={focus} onChange={setFocus} /> : null}
              {classes.length > 0 ? (
                <select
                  aria-label="Filter by class"
                  value={activeClass}
                  onChange={(e) => setClassFilter(e.target.value)}
                  className={SELECT_CLASS}
                >
                  <option value="">All classes</option>
                  {classes.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              ) : null}
              {categories.length > 0 ? (
                <select
                  aria-label="Filter by category"
                  value={activeCategory}
                  onChange={(e) => setCategoryFilter(e.target.value)}
                  className={SELECT_CLASS}
                >
                  <option value="">All categories</option>
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              ) : null}
              {terms.length > 0 ? (
                <select
                  aria-label="Filter by term"
                  value={activeTerm}
                  onChange={(e) => setTermFilter(e.target.value)}
                  className={SELECT_CLASS}
                >
                  <option value="">All terms</option>
                  {terms.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              ) : null}
          </div>

          <Tabs value={tab} onValueChange={setTab}>
            <TabsList>
              <TabsTrigger value="list">List</TabsTrigger>
              <TabsTrigger value="calendar">Calendar</TabsTrigger>
            </TabsList>

            <TabsContent value="list" className="flex flex-col gap-4 pt-4">
              <SearchInput value={rawQuery} onChange={setRawQuery} placeholder="Search events…" />
              {selectedIds.length > 0 ? (
                <div
                  role="region"
                  aria-label="Bulk actions"
                  className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-hairline bg-surface-2 px-4 py-2"
                >
                  <span className="text-body-sm text-ink">
                    {selectedIds.length} selected
                  </span>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" onClick={() => bulkSetStatus("archived")} loading={bulkBusy}>
                      Archive
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => bulkSetStatus("active")}
                      loading={bulkBusy}
                    >
                      Restore
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())} disabled={bulkBusy}>
                      Clear
                    </Button>
                  </div>
                </div>
              ) : null}
              {total === 0 ? (
                <EmptyState title="No matching events" description="Try a different search or filter." />
              ) : (
                <>
                  <Card className="overflow-hidden">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-10">
                            <input
                              type="checkbox"
                              checked={allOnPageSelected}
                              onChange={toggleAllOnPage}
                              aria-label="Select all events on this page"
                              className="size-4 rounded border-hairline text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            />
                          </TableHead>
                          <SortableHead label="Name" sortKey="name" activeKey={sort} dir={dir} onSort={onSort} />
                          <TableHead>Category</TableHead>
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
                              <input
                                type="checkbox"
                                checked={selected.has(event.id)}
                                onChange={() => toggleEvent(event.id)}
                                aria-label={`Select ${event.name}`}
                                className="size-4 rounded border-hairline text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                              />
                            </TableCell>
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
                              {(event.term || event.student_group_name) ? (
                                <span className="text-body-sm text-ink-muted">
                                  {[event.term, event.student_group_name]
                                    .filter(Boolean)
                                    .join(" · ")}
                                </span>
                              ) : null}
                            </TableCell>
                            <TableCell>
                              <CategoryBadge
                                categoryId={event.category_id}
                                categoryName={event.category_name}
                              />
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
            </TabsContent>

            <TabsContent value="calendar" className="pt-4">
              <CalendarView
                categoryId={activeCategory}
                term={activeTerm}
                status={filter}
                classId={activeClass}
                mine={focusOn}
              />
            </TabsContent>
          </Tabs>
        </div>
      )}
    </div>
  );
}
