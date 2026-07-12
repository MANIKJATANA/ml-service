import type { EnrollmentStatus } from "@/lib/api/types";

/**
 * Enrollment status → StatusPill tone + human label. Single source of truth, used
 * by the students list and the student-detail screen (decisions/0033).
 */
export const ENROLL_TONE: Record<EnrollmentStatus, "success" | "warning" | "error"> = {
  pending: "warning",
  enrolled: "success",
  failed: "error",
};

export const ENROLL_LABEL: Record<EnrollmentStatus, string> = {
  pending: "Pending",
  enrolled: "Enrolled",
  failed: "Failed",
};
