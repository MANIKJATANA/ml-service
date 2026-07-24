"use client";

import useSWR from "swr";

import { getSchool, getSchoolAdmins, getSchools } from "@/lib/api/endpoints";
import type { SchoolWithRollup, UserResponse } from "@/lib/api/types";
import { type ListQuery, useInfiniteList } from "@/lib/hooks/use-infinite-list";

/** One server page at a time of the platform schools list (BP9). */
export function useSchools(query: ListQuery) {
  return useInfiniteList<SchoolWithRollup>("schools", query, getSchools);
}

export function useSchool(schoolId: string) {
  const { data, error, isLoading, mutate } = useSWR<SchoolWithRollup>(
    schoolId ? `schools/${schoolId}` : null,
    () => getSchool(schoolId),
  );
  return { school: data, error, isLoading, mutate };
}

/** One server page at a time of a school's administrator roster (BP9). */
export function useSchoolAdmins(schoolId: string, query: ListQuery) {
  return useInfiniteList<UserResponse>(
    schoolId ? `schools/${schoolId}/admins` : null,
    query,
    (params) => getSchoolAdmins(schoolId, params),
  );
}
