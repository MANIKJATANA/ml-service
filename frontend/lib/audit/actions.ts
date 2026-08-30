/** Human labels + filter options for the admin-action audit (BP28b — the governance actor
 *  trail). The backend's `action` vocabulary is a bounded, closed set; this maps each value to
 *  a plain-language label. An unknown value (a future action not yet mapped here) falls back to
 *  a humanized form so the log never shows a raw enum. */

/** action → a short human label ("Created student", etc.). */
export const ACTION_LABELS: Record<string, string> = {
  student_created: "Created student",
  student_disabled: "Disabled student login",
  student_enabled: "Enabled student login",
  student_deleted: "Deleted student",
  student_reenrolled: "Re-enrolled student photo",
  student_invite_resent: "Resent student invite",
  staff_created: "Invited staff",
  staff_disabled: "Disabled staff login",
  staff_enabled: "Enabled staff login",
  staff_invite_resent: "Resent staff invite",
  school_updated: "Updated school",
};

/** A readable label for an action value (falls back to a humanized form for an unmapped one). */
export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action.replace(/_/g, " ");
}

/** The action-filter options (a select over the closed vocabulary). "" = all. */
export const ACTION_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All actions" },
  ...Object.entries(ACTION_LABELS).map(([value, label]) => ({ value, label })),
];

/** The target-type filter options. "" = all. */
export const TARGET_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All targets" },
  { value: "student", label: "Students" },
  { value: "staff", label: "Staff" },
  { value: "school", label: "School" },
];

/** A readable label for a target type ('student' → "Student"). */
export function targetTypeLabel(targetType: string): string {
  switch (targetType) {
    case "student":
      return "Student";
    case "staff":
      return "Staff";
    case "school":
      return "School";
    default:
      return targetType;
  }
}
