"use client";

import {
  Building2,
  CalendarDays,
  GraduationCap,
  Images,
  LayoutDashboard,
  LogOut,
  type LucideIcon,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { mutate } from "swr";

import { logout } from "@/lib/api/endpoints";
import type { Role, UserResponse } from "@/lib/api/types";
import { ROLE_LABELS } from "@/lib/auth/routes";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

// Nav is filtered to the caller's role. Targets not yet built (F2–F6) render a
// "coming soon" placeholder so the shell is fully navigable from F1.
const NAV_BY_ROLE: Record<Role, NavItem[]> = {
  platform_admin: [{ href: "/schools", label: "Schools", icon: Building2 }],
  school_admin: [
    { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
    { href: "/staff", label: "Staff", icon: Users },
    { href: "/students", label: "Students", icon: GraduationCap },
    { href: "/events", label: "Events", icon: CalendarDays },
  ],
  teacher: [
    { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
    { href: "/students", label: "Students", icon: GraduationCap },
    { href: "/events", label: "Events", icon: CalendarDays },
  ],
  student: [{ href: "/me/events", label: "My Photos", icon: Images }],
};

export function AppShell({ user, children }: { user: UserResponse; children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const items = NAV_BY_ROLE[user.role];

  async function handleLogout() {
    try {
      await logout();
    } catch {
      // Clear-and-go regardless; the cookies are cleared server-side on success,
      // and proxy.ts will bounce to /login if they weren't.
    }
    // Drop the cached user so nothing reads a stale session after logout.
    await mutate("auth/me", undefined, { revalidate: false });
    router.replace("/login");
    router.refresh();
  }

  return (
    <div className="flex min-h-dvh bg-surface">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-hairline bg-canvas sm:flex">
        <div className="flex h-14 items-center border-b border-hairline px-5">
          <span className="text-headline text-ink">Photos</span>
        </div>
        <nav className="flex flex-1 flex-col gap-0.5 p-3">
          {items.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-3 rounded-button px-3 py-2 text-body font-medium transition-colors",
                  active
                    ? "bg-surface-2 text-accent-hover"
                    : "text-ink-secondary hover:bg-surface hover:text-ink",
                )}
              >
                <Icon className="size-4 shrink-0" aria-hidden="true" />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-hairline p-3">
          <div className="flex flex-col gap-0.5 px-2 pb-2">
            <span className="truncate text-body-sm font-medium text-ink" title={user.email}>
              {user.email}
            </span>
            <span className="text-body-sm text-ink-muted">{ROLE_LABELS[user.role]}</span>
          </div>
          <button
            type="button"
            onClick={handleLogout}
            className="flex w-full items-center gap-3 rounded-button px-3 py-2 text-body font-medium text-ink-secondary transition-colors hover:bg-surface hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <LogOut className="size-4 shrink-0" aria-hidden="true" />
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b border-hairline bg-canvas px-4 sm:hidden">
          <span className="text-headline text-ink">Photos</span>
          <button
            type="button"
            onClick={handleLogout}
            aria-label="Sign out"
            className="rounded-button text-ink-secondary hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <LogOut className="size-5" />
          </button>
        </header>
        <main className="flex-1 p-4 sm:p-8">
          <div className="mx-auto w-full max-w-6xl">{children}</div>
        </main>
      </div>
    </div>
  );
}
