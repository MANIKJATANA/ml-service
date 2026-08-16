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
 * BP21 (R3-A2-07): a *photoless* student (no reference photo yet — e.g. bulk-imported) isn't
 * really "Pending enrollment" waiting on the system; the next action is the staff's — add a
 * photo. Show "No photo yet" (neutral) instead of the amber "Pending" pill. Any student WITH a
 * photo uses the real enrollment status. The single source for the pill on the list + detail.
 */
export function enrollDisplay(student: {
  enrollment_status: EnrollmentStatus;
  reference_photo_path: string | null;
}): { tone: "success" | "warning" | "error" | "neutral"; label: string } {
  if (student.reference_photo_path === null && student.enrollment_status === "pending") {
    return { tone: "neutral", label: "No photo yet" };
  }
  return {
    tone: ENROLL_TONE[student.enrollment_status],
    label: ENROLL_LABEL[student.enrollment_status],
  };
}

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
