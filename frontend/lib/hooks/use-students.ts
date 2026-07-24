"use client";

import useSWR from "swr";

import { getStudent, getStudents } from "@/lib/api/endpoints";
import type { StudentListItem, StudentResponse } from "@/lib/api/types";
import { type ListQuery, useInfiniteList } from "@/lib/hooks/use-infinite-list";

/** One server page at a time of the students list (BP9): search/sort/filter hit SQL. */
export function useStudents(query: ListQuery) {
  return useInfiniteList<StudentListItem>("students", query, getStudents);
}

export function useStudent(studentId: string) {
  const { data, error, isLoading, mutate } = useSWR<StudentResponse>(
    studentId ? `students/${studentId}` : null,
    () => getStudent(studentId),
  );
  return { student: data, error, isLoading, mutate };
}
