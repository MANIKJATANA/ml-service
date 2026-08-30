"use client";

import { MessageCircle } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import { useWhatsAppSend } from "@/lib/hooks/use-whatsapp-send";

interface SendPhotosButtonProps {
  studentId: string;
  studentName: string;
  /** The effective media ids to send (the same set the surface already shows). */
  mediaIds: string[];
  optedIn: boolean;
  hasNumber: boolean;
  /** Compact variant for a per-row/tab placement (defaults to a full-size secondary button). */
  size?: "sm" | "md";
}

/**
 * "Send N photos over WhatsApp" (W2). Student-centric: the SERVER loops best-effort per media
 * under one monthly budget — this button just confirms + fires one call. Disabled (with a
 * reason hint) when the student hasn't opted in or has no number on file. On resolve it toasts
 * an honest summary ("Sent X of N", + failed/skipped). a11y: an SR-only live region announces
 * the summary; the disabled-reason is surfaced as a hint. The recipient number never appears.
 */
export function SendPhotosButton({
  studentId,
  studentName,
  mediaIds,
  optedIn,
  hasNumber,
  size = "md",
}: SendPhotosButtonProps) {
  const { toast } = useToast();
  const { busy, send } = useWhatsAppSend(studentId);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [summary, setSummary] = useState<string>("");

  const n = mediaIds.length;
  const disabledReason = !optedIn
    ? "Student hasn't opted in to WhatsApp"
    : !hasNumber
      ? "No mobile number on file"
      : n === 0
        ? "No photos to send"
        : null;
  const disabled = disabledReason !== null;

  async function onConfirm() {
    setConfirmOpen(false);
    try {
      const res = await send(mediaIds);
      // Distinguish an over-budget skip (the school hit its monthly WhatsApp limit) from a
      // plain skip — the data is already per-media on the wire, and staff need to know when
      // they've exhausted their paid quota vs a photo simply wasn't entitled.
      const budgetSkipped = res.results.filter(
        (r) => r.status === "skipped" && r.reason === "budget",
      ).length;
      const otherSkipped = res.skipped - budgetSkipped;
      const extra: string[] = [];
      if (res.failed > 0) extra.push(`${res.failed} failed`);
      if (budgetSkipped > 0)
        extra.push(`${budgetSkipped} skipped (monthly WhatsApp limit reached)`);
      if (otherSkipped > 0) extra.push(`${otherSkipped} skipped`);
      const tail = extra.length > 0 ? ` ${extra.join(", ")}.` : "";
      const line = `Sent ${res.sent} of ${n} ${n === 1 ? "photo" : "photos"}.${tail}`;
      // Keep the SR-only summary consistent in tone with the toast on the all-failed path.
      setSummary(res.sent === 0 ? `Couldn't send any photos.${tail}` : line);
      if (res.sent === 0) {
        toast(`Couldn't send.${tail || " Please try again."}`, "error");
      } else if (res.failed > 0 || res.skipped > 0) {
        toast(line, "info", { sticky: true });
      } else {
        toast(line, "success");
      }
    } catch {
      // A 400 (not opted in / disabled) or a 502 is surfaced as an error toast; the button
      // stays enabled so staff can retry after fixing the cause.
      toast("Couldn't send the photos. Please try again.", "error");
    }
  }

  return (
    <div className="flex items-center gap-3">
      <Button
        variant="secondary"
        size={size === "sm" ? "sm" : undefined}
        onClick={() => setConfirmOpen(true)}
        loading={busy}
        disabled={disabled || busy}
        title={disabledReason ?? undefined}
      >
        <MessageCircle className="size-4" aria-hidden="true" />
        {busy ? "Sending…" : `Send ${n} on WhatsApp`}
      </Button>
      {disabledReason ? (
        <span className="text-body-sm text-ink-secondary">{disabledReason}</span>
      ) : null}
      {/* SR-only summary — announced once on resolve (the toast covers sighted users). */}
      <span className="sr-only" aria-live="polite">
        {summary}
      </span>
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Send photos on WhatsApp?"
        description={`Send ${n} ${n === 1 ? "photo" : "photos"} to ${studentName} — this uses ${n} WhatsApp ${n === 1 ? "message" : "messages"}.`}
        confirmLabel={`Send ${n}`}
        onConfirm={onConfirm}
      />
    </div>
  );
}
