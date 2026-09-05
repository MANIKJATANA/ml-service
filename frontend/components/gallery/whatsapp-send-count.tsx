"use client";

import { MessageCircle } from "lucide-react";

import { useMediaWhatsAppLog } from "@/lib/hooks/use-galleries";

/** A small staff-only line: how many times this photo/video was actually SENT on WhatsApp — the
 *  per-photo cost count (each send is one message, so a photo sent to N students counts N). Reads
 *  the append-only send log (nothing is sent). Renders nothing until the count resolves (loading /
 *  error / not enabled → null). `enabled` gates the fetch: the endpoint is `gallery:view_all`, so a
 *  student surface (the `/me` lightbox) MUST pass `false` — defence in depth beside the server gate. */
export function WhatsAppSendCount({
  mediaId,
  enabled = true,
}: {
  mediaId: string;
  enabled?: boolean;
}) {
  const { sentCount } = useMediaWhatsAppLog(mediaId, enabled);
  if (sentCount === null) return null;
  return (
    <p className="flex items-center gap-1.5 text-body-sm text-ink-secondary">
      <MessageCircle className="size-4 shrink-0" aria-hidden="true" />
      {sentCount === 0
        ? "Not sent on WhatsApp yet"
        : `Sent on WhatsApp ${sentCount} ${sentCount === 1 ? "time" : "times"}`}
    </p>
  );
}
