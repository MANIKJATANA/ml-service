"use client";

import { Archive, Images, Pencil, Play, RotateCcw, Upload } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useState } from "react";
import { mutate as globalMutate } from "swr";

import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { ProgressBar } from "@/components/ui/progress-bar";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { processEvent, updateEvent } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { EventProcessingStatus, EventResponse } from "@/lib/api/types";
import {
  EVENT_STATUS_LABEL,
  EVENT_STATUS_TONE,
  PROCESSING_LABEL,
  PROCESSING_TONE,
} from "@/lib/events/status";
import { useEvent } from "@/lib/hooks/use-events";
import { useEventStatus } from "@/lib/hooks/use-event-status";
import { formatDate } from "@/lib/utils";

function EditEventDialog({
  event,
  onSaved,
}: {
  event: EventResponse;
  onSaved: (event: EventResponse) => void;
}) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(event.name);
  const [description, setDescription] = useState(event.description ?? "");
  const [eventDate, setEventDate] = useState(event.event_date ?? "");
  const [submitting, setSubmitting] = useState(false);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (next) {
      // Re-seed from the latest event each time it opens.
      setName(event.name);
      setDescription(event.description ?? "");
      setEventDate(event.event_date ?? "");
    }
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    // Send only changed fields. The backend can't clear a field to null (0027), so an
    // emptied optional field is omitted (left unchanged) rather than cleared.
    const patch: { name?: string; description?: string; event_date?: string } = {};
    if (name.trim() && name.trim() !== event.name) patch.name = name.trim();
    if (description.trim() && description.trim() !== (event.description ?? "")) {
      patch.description = description.trim();
    }
    if (eventDate && eventDate !== (event.event_date ?? "")) patch.event_date = eventDate;
    if (Object.keys(patch).length === 0) {
      toast("No changes to save.", "info");
      setOpen(false);
      return;
    }
    setSubmitting(true);
    try {
      const updated = await updateEvent(event.id, patch);
      toast("Event updated.", "success");
      onSaved(updated);
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
          Edit
        </Button>
      </DialogTrigger>
      <DialogContent title="Edit event" description="Emptying an optional field leaves it unchanged.">
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <Field label="Name" htmlFor="edit-event-name">
            <Input
              id="edit-event-name"
              required
              autoFocus
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label="Description" htmlFor="edit-event-description" hint="Optional.">
            <Textarea
              id="edit-event-description"
              maxLength={2000}
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <Field label="Date" htmlFor="edit-event-date" hint="Optional.">
            <Input
              id="edit-event-date"
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
              Save changes
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function EventDetailPage() {
  const { eventId } = useParams<{ eventId: string }>();
  const { toast } = useToast();
  const { event, isLoading, error, mutate: eventMutate } = useEvent(eventId);
  const { status, isLoading: statusLoading, mutate: statusMutate } = useEventStatus(eventId);

  const [processing, setProcessing] = useState(false);
  const [lifecycleBusy, setLifecycleBusy] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);

  const notFound = isApiError(error) && error.status === 404;

  async function onProcess() {
    if (!event) return;
    setProcessing(true);
    try {
      const updated = await processEvent(event.id);
      await eventMutate(updated, { revalidate: false });
      void globalMutate("events");
      // Optimistically flip status to queued so the pill + poll re-arm at once (even if the
      // refetch is slow or fails); revalidate to pull fresh counts.
      await statusMutate(
        (prev) => (prev ? { ...prev, processing_status: "queued" as const } : prev),
        { revalidate: true },
      );
      toast("Distribution started.", "success");
    } catch (err) {
      // 400 archived / already in flight / no pending photos; 502 if the queue is down.
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setProcessing(false);
    }
  }

  async function setLifecycle(next: "active" | "archived") {
    if (!event) return;
    setLifecycleBusy(true);
    try {
      const updated = await updateEvent(event.id, { status: next });
      await eventMutate(updated, { revalidate: false });
      void globalMutate("events");
      toast(next === "archived" ? "Event archived." : "Event restored.", "success");
      setArchiveOpen(false);
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setLifecycleBusy(false);
    }
  }

  const isArchived = event?.status === "archived";
  const proc = status?.processing_status ?? event?.processing_status ?? "not_started";
  const inFlight = proc === "queued" || proc === "processing";
  // The pill must not contradict the counts: after a completed run + new uploads the
  // backend keeps processing_status="completed" while pending > 0. When nothing is in
  // flight and we have counts, reflect the outstanding work rather than the stale status.
  let pillStatus: EventProcessingStatus = proc;
  if (!inFlight && status) {
    pillStatus = status.total > 0 && status.pending === 0 ? "completed" : "not_started";
  }

  return (
    <div className="flex flex-col gap-6">
      <Breadcrumb
        items={[{ label: "Events", href: "/events" }, { label: event?.name ?? "Event" }]}
      />

      {isLoading ? (
        <>
          <Skeleton className="h-9 w-64" />
          <Card className="flex flex-col gap-3 p-6">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-4 w-32" />
          </Card>
        </>
      ) : error || !event ? (
        <EmptyState
          title={notFound ? "Event not found" : "Couldn't load event"}
          description={
            notFound ? "It may have been removed." : "Something went wrong reaching the server."
          }
          action={
            notFound ? undefined : (
              <Button variant="secondary" onClick={() => eventMutate()}>
                Retry
              </Button>
            )
          }
        />
      ) : (
        <>
          <PageHeader
            title={event.name}
            actions={
              <>
                {status && status.total > 0 ? (
                  <Link
                    href={`/events/${event.id}/gallery`}
                    className={buttonVariants({ variant: "secondary" })}
                  >
                    <Images className="size-4" aria-hidden="true" />
                    View gallery
                  </Link>
                ) : null}
                <EditEventDialog
                  event={event}
                  onSaved={(e) => eventMutate(e, { revalidate: false })}
                />
                {isArchived ? (
                  <Button
                    variant="secondary"
                    onClick={() => void setLifecycle("active")}
                    loading={lifecycleBusy}
                  >
                    <RotateCcw className="size-4" aria-hidden="true" />
                    Restore
                  </Button>
                ) : (
                  <Button variant="secondary" onClick={() => setArchiveOpen(true)}>
                    <Archive className="size-4" aria-hidden="true" />
                    Archive
                  </Button>
                )}
              </>
            }
          />

          <Card className="p-6">
            <div className="flex flex-col gap-6">
              {event.description ? (
                <p className="whitespace-pre-wrap text-body text-ink-secondary">
                  {event.description}
                </p>
              ) : null}
              <dl className="grid gap-6 sm:grid-cols-3">
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-muted">Date</dt>
                  <dd className="text-body text-ink">
                    {event.event_date ? formatDate(event.event_date) : "—"}
                  </dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-muted">Status</dt>
                  <dd>
                    <StatusPill tone={EVENT_STATUS_TONE[event.status]}>
                      {EVENT_STATUS_LABEL[event.status]}
                    </StatusPill>
                  </dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-body-sm text-ink-muted">Created</dt>
                  <dd className="text-body text-ink">{formatDate(event.created_at)}</dd>
                </div>
              </dl>
            </div>
          </Card>

          <Card className="flex flex-col gap-4 p-6">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-headline text-ink">Photos</h2>
              <StatusPill tone={PROCESSING_TONE[pillStatus]}>
                {PROCESSING_LABEL[pillStatus]}
              </StatusPill>
            </div>

            {statusLoading && !status ? (
              <div className="flex flex-col gap-2">
                <Skeleton className="h-2 w-full" />
                <Skeleton className="h-4 w-48" />
              </div>
            ) : !status ? (
              <p className="text-body-sm text-ink-secondary">Couldn&apos;t load photo status.</p>
            ) : (
              <>
                {status.total > 0 ? (
                  <>
                    <ProgressBar
                      value={(status.completed / status.total) * 100}
                      label="Processing progress"
                    />
                    <p className="text-body-sm text-ink-secondary">
                      {status.completed} of {status.total} processed
                      {status.pending > 0 ? ` · ${status.pending} pending` : ""}
                    </p>
                  </>
                ) : (
                  <p className="text-body-sm text-ink-secondary">No photos uploaded yet.</p>
                )}

                {isArchived ? (
                  <p className="text-body-sm text-ink-secondary">
                    Archived — restore the event to upload or distribute.
                  </p>
                ) : (
                  <div className="flex flex-wrap items-center gap-2">
                    <Link
                      href={`/events/${event.id}/upload`}
                      className={buttonVariants({
                        variant: status.total === 0 ? "primary" : "secondary",
                      })}
                    >
                      <Upload className="size-4" aria-hidden="true" />
                      {status.total === 0 ? "Upload photos" : "Add more photos"}
                    </Link>
                    {!inFlight && status.pending > 0 ? (
                      <Button onClick={onProcess} loading={processing}>
                        <Play className="size-4" aria-hidden="true" />
                        {proc === "completed" ? "Redistribute" : "Process photos"}
                      </Button>
                    ) : null}
                  </div>
                )}

                <div aria-live="polite">
                  {!isArchived && inFlight ? (
                    <p className="text-body-sm text-ink-secondary">
                      Distribution is running — this updates automatically.
                    </p>
                  ) : null}
                  {!isArchived && !inFlight && status.total > 0 && status.pending === 0 ? (
                    <p className="text-body-sm text-success-strong">All photos processed.</p>
                  ) : null}
                </div>
              </>
            )}
          </Card>
        </>
      )}

      <ConfirmDialog
        open={archiveOpen}
        onOpenChange={setArchiveOpen}
        title="Archive event?"
        description="Its photos are kept, but it's hidden from active workflows. You can restore it anytime."
        confirmLabel="Archive event"
        loading={lifecycleBusy}
        onConfirm={() => void setLifecycle("archived")}
      />
    </div>
  );
}
