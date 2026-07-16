import type { EnrollmentFailureReason, EnrollmentStatus } from "@/lib/api/types";

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

/**
 * A failed enrollment's reason → a compact list label + a detail-page explanation and
 * fix (BP7b, decisions/0045). `no_face`/`error` need a better photo (**Replace photo** on
 * the student detail — BP7d-2); `ml_unavailable` is transient — just retry.
 */
export const ENROLL_FAILURE_SHORT: Record<EnrollmentFailureReason, string> = {
  no_face: "No clear face",
  ml_unavailable: "Service unavailable",
  error: "Couldn't process photo",
};

export const ENROLL_FAILURE_HELP: Record<
  EnrollmentFailureReason,
  { title: string; fix: string }
> = {
  no_face: {
    title: "No clear face was found in the reference photo",
    fix: "Use Replace photo to upload a sharp, well-lit photo showing the student's face straight-on.",
  },
  ml_unavailable: {
    title: "The matching service was unavailable",
    fix: "This is usually temporary. Wait a moment, then re-enroll to try again.",
  },
  error: {
    title: "This photo couldn't be processed",
    fix: "Use Replace photo to upload a different photo (a standard JPEG or PNG).",
  },
};
