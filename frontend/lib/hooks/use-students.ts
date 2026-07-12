"use client";

import useSWR from "swr";

import { getStudent, listStudents } from "@/lib/api/endpoints";
import type { StudentResponse } from "@/lib/api/types";

export function useStudents() {
  const { data, error, isLoading, mutate } = useSWR<StudentResponse[]>("students", listStudents);
  return { students: data, error, isLoading, mutate };
}

export function useStudent(studentId: string) {
  const { data, error, isLoading, mutate } = useSWR<StudentResponse>(
    studentId ? `students/${studentId}` : null,
    () => getStudent(studentId),
  );
  return { student: data, error, isLoading, mutate };
}
