"use client";

import { useState } from "react";

import { sendWhatsApp } from "@/lib/api/endpoints";
import type { WhatsAppSendResponse } from "@/lib/api/types";

/**
 * A thin action hook for the WhatsApp send (W2). The SERVER loops best-effort per media under
 * one monthly budget — this is NOT a browser pool, just a single call + a `busy` flag. Returns
 * the response so the caller can surface an honest summary toast ("Sent X of N").
 */
export function useWhatsAppSend(studentId: string) {
  const [busy, setBusy] = useState(false);

  async function send(mediaIds: string[] | null): Promise<WhatsAppSendResponse> {
    setBusy(true);
    try {
      return await sendWhatsApp(studentId, mediaIds);
    } finally {
      setBusy(false);
    }
  }

  return { busy, send };
}
