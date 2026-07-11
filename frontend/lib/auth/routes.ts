import type { Role } from "@/lib/api/types";

/**
 * Where each role lands after login — also used to bounce a role out of a route
 * group it isn't allowed in (decisions/0031). Pure (no icons/JSX) so it's usable
 * from both the client guard and future server code.
 */
export function homePathForRole(role: Role): string {
  switch (role) {
    case "platform_admin":
      return "/schools";
    case "student":
      return "/me/events";
    case "school_admin":
    case "teacher":
      return "/dashboard";
  }
}

/** Human-readable role label (sidebar + dashboard). */
export const ROLE_LABELS: Record<Role, string> = {
  platform_admin: "Platform admin",
  school_admin: "School admin",
  teacher: "Teacher",
  student: "Student",
};
