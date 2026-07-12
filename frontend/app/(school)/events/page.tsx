"use client";

import { CalendarDays, Plus } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useState } from "react";

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
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { createEvent } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import {
  EVENT_STATUS_LABEL,
  EVENT_STATUS_TONE,
  PROCESSING_LABEL,
  PROCESSING_TONE,
} from "@/lib/events/status";
import { useEvents } from "@/lib/hooks/use-events";
import { formatDate } from "@/lib/utils";

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
  const { events, isLoading, error, mutate } = useEvents();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Events"
        description="Upload event photos and distribute them to the students who appear."
        actions={<CreateEventDialog onCreated={() => mutate()} />}
      />

      {isLoading ? (
        <Card className="flex flex-col gap-2 p-4">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-11 w-full" />
          ))}
        </Card>
      ) : error ? (
        <EmptyState
          title="Couldn't load events"
          description="Something went wrong reaching the server."
          action={
            <Button variant="secondary" onClick={() => mutate()}>
              Retry
            </Button>
          }
        />
      ) : !events || events.length === 0 ? (
        <EmptyState
          icon={<CalendarDays className="size-8" aria-hidden="true" />}
          title="No events yet"
          description="Create an event, upload its photos, and run distribution."
          action={<CreateEventDialog onCreated={() => mutate()} />}
        />
      ) : (
        <Card className="overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Date</TableHead>
                <TableHead>Processing</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map((event) => (
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
      )}
    </div>
  );
}
