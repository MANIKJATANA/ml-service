"use client";

import { getStaff } from "@/lib/api/endpoints";
import type { UserResponse } from "@/lib/api/types";
import { type ListQuery, useInfiniteList } from "@/lib/hooks/use-infinite-list";

/** One server page at a time of the teacher roster (BP9): search (email) + sort hit SQL. */
export function useStaff(query: ListQuery) {
  return useInfiniteList<UserResponse>("staff", query, getStaff);
}
