import type { ReactNode } from "react";

import { AuthGuard } from "@/components/auth-guard";

export default function PlatformLayout({ children }: { children: ReactNode }) {
  return <AuthGuard allow={["platform_admin"]}>{children}</AuthGuard>;
}
