"use client";

import useSWR from "swr";

import { listStaff } from "@/lib/api/endpoints";
import type { UserResponse } from "@/lib/api/types";

export function useStaff() {
  const { data, error, isLoading, mutate } = useSWR<UserResponse[]>("staff", listStaff);
  return { staff: data, error, isLoading, mutate };
}
