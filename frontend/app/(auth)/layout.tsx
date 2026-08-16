import { Images } from "lucide-react";
import type { ReactNode } from "react";

/** Centered layout for the sign-in / change-password screens — with a brand moment (BP25) so a
 *  student's first impression isn't a bare gray card, and a proper landmark `<main>`. */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center bg-surface px-4 py-12">
      <div className="mb-8 flex items-center gap-2 text-accent-hover">
        <Images className="size-7" aria-hidden="true" />
        <span className="text-display-md font-semibold tracking-tight">Photos</span>
      </div>
      <div className="w-full max-w-sm">{children}</div>
    </main>
  );
}
