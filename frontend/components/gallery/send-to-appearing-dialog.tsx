"use client";

import { useState } from "react";
import useSWR from "swr";

import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { eventPhotoRecipients, sendEventPhotos } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { EventPhotoRecipient } from "@/lib/api/types";

/** Preview + confirm the event-photo fan-out ("send selected photos to whoever appears"). Opens
 *  on the "All photos" tab's selection: fetches who effectively appears in the SELECTED photos +
 *  whether they can receive (opted in + a number), shows the totals ("N students · X messages ·
 *  M skipped"), and — only on confirm — fans the photos out (each student gets the subset they
 *  appear in). The server does all the gating (consent, budget, effective overlay, PII); this is
 *  just the "show once" preview + the send call. */
export function SendToAppearingDialog({
  eventId,
  mediaIds,
  open,
  onOpenChange,
  onSent,
}: {
  eventId: string;
  mediaIds: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after a successful send (e.g. to exit select mode). */
  onSent?: () => void;
}) {
  const { toast } = useToast();
  const [sending, setSending] = useState(false);

  // Media ids (UUIDs, comma-free) as a stable SWR key so the preview fetches once per selection.
  // A null key while closed means SWR doesn't fetch; opening (or a new selection) triggers it.
  const mediaKey = mediaIds.join(",");
  const { data, error, isLoading } = useSWR(
    open ? ["event-photo-recipients", eventId, mediaKey] : null,
    () => eventPhotoRecipients(eventId, mediaKey ? mediaKey.split(",") : []),
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
      const res = await sendEventPhotos(eventId, mediaKey ? mediaKey.split(",") : []);
      if (res.sent === 0) {
        toast("Couldn't send the photos. Please try again.", "error");
      } else {
        const tail = res.students_skipped > 0 ? ` · ${res.students_skipped} skipped` : "";
        const photos = res.sent === 1 ? "photo" : "photos";
        const studs = res.students_sent === 1 ? "student" : "students";
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

  const n = mediaIds.length;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={`Send ${n} ${n === 1 ? "photo" : "photos"} on WhatsApp?`}
        description="Each student gets only the photos they appear in."
      >
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
            No students appear in the selected photos.
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
