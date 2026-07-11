import type { ReactNode } from "react";

import { AuthGuard } from "@/components/auth-guard";

export default function SchoolLayout({ children }: { children: ReactNode }) {
  return <AuthGuard allow={["school_admin", "teacher"]}>{children}</AuthGuard>;
}
