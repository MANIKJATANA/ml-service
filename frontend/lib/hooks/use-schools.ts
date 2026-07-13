"use client";

import useSWR from "swr";

import { getSchool, listSchoolAdmins, listSchools } from "@/lib/api/endpoints";
import type { SchoolWithRollup, UserResponse } from "@/lib/api/types";

export function useSchools() {
  const { data, error, isLoading, mutate } = useSWR<SchoolWithRollup[]>("schools", listSchools);
  return { schools: data, error, isLoading, mutate };
}

export function useSchool(schoolId: string) {
  const { data, error, isLoading, mutate } = useSWR<SchoolWithRollup>(
    schoolId ? `schools/${schoolId}` : null,
    () => getSchool(schoolId),
  );
  return { school: data, error, isLoading, mutate };
}

export function useSchoolAdmins(schoolId: string) {
  const { data, error, isLoading, mutate } = useSWR<UserResponse[]>(
    schoolId ? `schools/${schoolId}/admins` : null,
    () => listSchoolAdmins(schoolId),
  );
  return { admins: data, error, isLoading, mutate };
}
