"use client";

import { useState } from "react";
import useSWR from "swr";

import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { eventPhotoRecipients, sendEventPhotos } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { EventPhotoRecipient } from "@/lib/api/types";

/** Preview + confirm the event-photo fan-out. Two modes, one component:
 *   • SELECTED photos — pass `mediaIds` (the "All photos" tab's selection).
 *   • the WHOLE event ("Announce on WhatsApp", from the event's Announce card) — omit `mediaIds`.
 *  Fetches who effectively appears + whether they can receive (opted in + a number), shows the
 *  totals ("N students · X messages · M skipped"), and — only on confirm — fans the photos out
 *  (each student gets the subset they appear in). The server does all the gating (consent, budget,
 *  effective overlay, PII); this is just the "show once" preview + the send call. */
export function SendToAppearingDialog({
  eventId,
  mediaIds,
  open,
  onOpenChange,
  onSent,
}: {
  eventId: string;
  /** The SELECTED photos to fan out; omit (undefined) to announce the WHOLE event. */
  mediaIds?: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after a successful send (e.g. to exit select mode). */
  onSent?: () => void;
}) {
  const { toast } = useToast();
  const [sending, setSending] = useState(false);

  // A stable SWR key so the preview fetches once per selection (or once for the whole event).
  // A null key while closed means SWR doesn't fetch; opening (or a new selection) triggers it.
  // `mediaIds ?? null` → the whole-event mode when omitted.
  const mediaKey = mediaIds ? mediaIds.join(",") : "ALL";
  const { data, error, isLoading } = useSWR(
    open ? ["event-photo-recipients", eventId, mediaKey] : null,
    () => eventPhotoRecipients(eventId, mediaIds ?? null),
  );
  const recipients: EventPhotoRecipient[] | null = data?.recipients ?? null;
  // Test mode: the server diverts every send to the test number regardless of consent, so allow
  // the send as long as SOMEONE appears (else the normal opted-in-with-a-number requirement).
  const interim = data?.interim ?? false;

  const eligible = (r: EventPhotoRecipient) => r.opted_in && r.has_number;
  const sendable = recipients?.filter(eligible) ?? [];
  const skipped = recipients?.filter((r) => !eligible(r)) ?? [];
  const totalMessages = sendable.reduce((sum, r) => sum + r.photo_count, 0);
  const canSend =
    (interim ? (recipients?.length ?? 0) > 0 : sendable.length > 0) && !sending;

  async function handleSend() {
    setSending(true);
    try {
      const res = await sendEventPhotos(eventId, mediaIds ?? null);
      if (res.sent === 0) {
        toast("Couldn't send the photos. Please try again.", "error");
      } else {
        const photos = res.sent === 1 ? "photo" : "photos";
        const studs = res.students_sent === 1 ? "student" : "students";
        // A sticky "partial" toast must always carry a visible REASON (consistency with the
        // per-student surface, which flags the monthly budget). Whole-student consent skips,
        // failures, and photos clipped by the budget each get a bit. `res.skipped` (photos)
        // already includes a fully-skipped student's photos, so the pure-photo remainder is only
        // surfaced when NO whole student was skipped — else the "N students skipped" bit is the
        // reason. This guarantees a sticky toast is never reasonless.
        const bits: string[] = [];
        if (res.students_skipped > 0) {
          bits.push(
            `${res.students_skipped} ${res.students_skipped === 1 ? "student" : "students"} skipped`,
          );
        }
        if (res.failed > 0) bits.push(`${res.failed} failed`);
        if (res.students_skipped === 0 && res.skipped > 0) {
          bits.push(
            `${res.skipped} ${res.skipped === 1 ? "photo" : "photos"} not sent (the monthly WhatsApp limit may be reached)`,
          );
        }
        const tail = bits.length > 0 ? ` · ${bits.join(" · ")}` : "";
        const partial = res.failed > 0 || res.skipped > 0;
        toast(
          `Sent ${res.sent} ${photos} to ${res.students_sent} ${studs}${tail}.`,
          partial ? "info" : "success",
          partial ? { sticky: true } : undefined,
        );
      }
      onOpenChange(false);
      onSent?.();
    } catch (err) {
      // A 400 ("WhatsApp is not configured…") or 502 surfaces its message; the dialog stays open.
      toast(isApiError(err) ? err.message : "Couldn't send the photos.", "error");
    } finally {
      setSending(false);
    }
  }

  const n = mediaIds?.length ?? 0;
  const title = mediaIds
    ? `Send ${n} ${n === 1 ? "photo" : "photos"} on WhatsApp?`
    : "Announce all photos on WhatsApp?";
  const description = mediaIds
    ? "Each student gets only the photos they appear in."
    : "Every student who appears gets the photos they're in — this can be many WhatsApp messages.";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={title} description={description}>
        {isLoading ? (
          <p role="status" className="py-4 text-body-sm text-ink-secondary">
            Checking who appears in these photos…
          </p>
        ) : error ? (
          <p role="alert" className="py-4 text-body-sm text-ink-secondary">
            Couldn&apos;t load the recipients. Please close and try again.
          </p>
        ) : recipients && recipients.length === 0 ? (
          <p className="py-4 text-body-sm text-ink-secondary">
            No students appear in {mediaIds ? "the selected photos" : "this event's photos"}.
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            <ul className="max-h-64 divide-y divide-hairline overflow-y-auto rounded-button border border-hairline">
              {(recipients ?? []).map((r) => {
                const ok = eligible(r);
                return (
                  <li
                    key={r.student_id}
                    className="flex items-center gap-3 px-3 py-2 text-body-sm"
                  >
                    <span className="min-w-0 flex-1 truncate text-ink">{r.name}</span>
                    {ok ? (
                      <span className="shrink-0 tabular-nums text-ink-secondary">
                        {r.photo_count} {r.photo_count === 1 ? "photo" : "photos"}
                      </span>
                    ) : (
                      <span className="shrink-0 text-ink-secondary">
                        {!r.opted_in ? "not opted in" : "no number"} · skip
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
            {interim ? (
              <p
                role="status"
                className="rounded-button bg-warning-soft px-3 py-2 text-body-sm text-warning-strong"
              >
                Test mode — all {recipients?.length ?? 0} recipients go to the test number, not the
                students.
              </p>
            ) : (
              <p role="status" className="text-body-sm text-ink-secondary">
                {sendable.length} {sendable.length === 1 ? "student" : "students"} ·{" "}
                {totalMessages} WhatsApp {totalMessages === 1 ? "message" : "messages"}
                {skipped.length > 0 ? ` · ${skipped.length} skipped` : ""}
              </p>
            )}
          </div>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <DialogClose asChild>
            <Button variant="secondary" disabled={sending}>
              Cancel
            </Button>
          </DialogClose>
          <Button onClick={handleSend} loading={sending} disabled={!canSend}>
            Send
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
