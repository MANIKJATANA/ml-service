import type { ReactNode } from "react";

/** Centered, chrome-free layout for the sign-in / change-password screens. */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-surface px-4 py-12">
      <div className="w-full max-w-sm">{children}</div>
    </div>
  );
}
