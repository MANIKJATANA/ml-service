"use client";

import useSWR from "swr";

import { getSchool, listSchools } from "@/lib/api/endpoints";
import type { SchoolResponse } from "@/lib/api/types";

export function useSchools() {
  const { data, error, isLoading, mutate } = useSWR<SchoolResponse[]>("schools", listSchools);
  return { schools: data, error, isLoading, mutate };
}

export function useSchool(schoolId: string) {
  const { data, error, isLoading, mutate } = useSWR<SchoolResponse>(
    schoolId ? `schools/${schoolId}` : null,
    () => getSchool(schoolId),
  );
  return { school: data, error, isLoading, mutate };
}
