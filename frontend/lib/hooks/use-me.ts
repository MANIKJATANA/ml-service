"use client";

import useSWR from "swr";

import { getMe } from "@/lib/api/endpoints";
import type { UserResponse } from "@/lib/api/types";

/**
 * The current authenticated user (GET /api/v1/auth/me via the BFF, with transparent
 * refresh-retry). A single stable SWR key so every consumer shares one request.
 */
export function useMe() {
  const { data, error, isLoading, mutate } = useSWR<UserResponse>("auth/me", getMe, {
    shouldRetryOnError: false,
    revalidateOnFocus: false,
  });
  return { user: data, error, isLoading, mutate };
}
