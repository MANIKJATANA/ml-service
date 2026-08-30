"use client";

import useSWR from "swr";

import { getWhatsAppConfig } from "@/lib/api/endpoints";
import type { WhatsAppConfigResponse } from "@/lib/api/types";

/**
 * The school's WhatsApp config (W1) — one fetch, school-admin only (`whatsapp:manage`). Keyed
 * on "whatsapp-config" so a save can `mutate("whatsapp-config")`. The provider secret is never
 * exposed here; this is the NON-SECRET per-school settings only.
 */
export function useWhatsAppConfig() {
  const { data, error, isLoading, mutate } = useSWR<WhatsAppConfigResponse>(
    "whatsapp-config",
    getWhatsAppConfig,
  );
  return { config: data, error, isLoading, mutate };
}
