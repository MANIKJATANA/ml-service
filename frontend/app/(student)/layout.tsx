import type { ReactNode } from "react";

import { AuthGuard } from "@/components/auth-guard";

export default function StudentLayout({ children }: { children: ReactNode }) {
  return <AuthGuard allow={["student"]}>{children}</AuthGuard>;
}
