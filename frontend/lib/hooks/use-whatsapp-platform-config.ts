"use client";

import useSWR from "swr";

import { getWhatsAppPlatformConfig } from "@/lib/api/endpoints";
import type { WhatsAppPlatformConfigResponse } from "@/lib/api/types";

/**
 * The platform-wide WhatsApp config (W-live-test) — platform-admin only. Keyed on
 * "whatsapp-platform-config" so a save can `mutate` it. The Meta token is never exposed here;
 * the response carries only `token_set` + `token_last4`.
 */
export function useWhatsAppPlatformConfig() {
  const { data, error, isLoading, mutate } = useSWR<WhatsAppPlatformConfigResponse>(
    "whatsapp-platform-config",
    getWhatsAppPlatformConfig,
  );
  return { config: data, error, isLoading, mutate };
}
