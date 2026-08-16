import type { ReactNode } from "react";

import { AuthGuard } from "@/components/auth-guard";

/** BP21: shared help pages (e.g. "How photo matching works") — reachable by every signed-in
 *  role (students from their empty state, staff from the review lane). */
export default function HelpLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard allow={["student", "teacher", "school_admin", "platform_admin"]}>
      {children}
    </AuthGuard>
  );
}
