"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import {
  BookOpen,
  Building2,
  CalendarDays,
  GraduationCap,
  Images,
  LayoutDashboard,
  LogOut,
  type LucideIcon,
  Menu,
  ScrollText,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";
import { mutate } from "swr";

import { logout } from "@/lib/api/endpoints";
import type { Role, UserResponse } from "@/lib/api/types";
import { ROLE_LABELS } from "@/lib/auth/routes";
import { useDashboard } from "@/lib/hooks/use-dashboard";
import { useMyNotifications } from "@/lib/hooks/use-my-notifications";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

/** A small attention count shown on a nav item (information scent). */
interface NavBadge {
  count: number;
  tone: "error" | "warning" | "accent";
  /** Screen-reader text for the badge; defaults to an "attention" phrasing. */
  label?: string;
}

const BADGE_TONE: Record<NavBadge["tone"], string> = {
  error: "bg-error-soft text-error-strong",
  warning: "bg-warning-soft text-warning-strong",
  accent: "bg-accent/10 text-accent-dark",
};

// Nav is filtered to the caller's role.
const NAV_BY_ROLE: Record<Role, NavItem[]> = {
  platform_admin: [{ href: "/schools", label: "Schools", icon: Building2 }],
  school_admin: [
    { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
    { href: "/staff", label: "Staff", icon: Users },
    { href: "/students", label: "Students", icon: GraduationCap },
    { href: "/classes", label: "Classes", icon: BookOpen },
    { href: "/events", label: "Events", icon: CalendarDays },
    { href: "/audit", label: "Access log", icon: ScrollText },
  ],
  teacher: [
    { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
    { href: "/students", label: "Students", icon: GraduationCap },
    { href: "/events", label: "Events", icon: CalendarDays },
  ],
  student: [{ href: "/me/events", label: "My Photos", icon: Images }],
};

/** Role-filtered nav links; shared by the desktop sidebar and the mobile drawer. */
function NavList({
  items,
  pathname,
  badges,
  onNavigate,
}: {
  items: NavItem[];
  pathname: string;
  badges?: Record<string, NavBadge>;
  onNavigate?: () => void;
}) {
  return (
    <nav className="flex flex-1 flex-col gap-0.5 p-3">
      {items.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        const Icon = item.icon;
        const badge = badges?.[item.href];
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
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
            {badge ? (
              <span
                className={cn(
                  "ml-auto rounded-full px-1.5 py-0.5 text-body-sm font-medium tabular-nums",
                  BADGE_TONE[badge.tone],
                )}
                aria-label={badge.label ?? `${badge.count} need attention`}
              >
                {badge.count}
              </span>
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}

/** Email + role + sign out; shared by the sidebar and the drawer. */
function UserFooter({ user, onSignOut }: { user: UserResponse; onSignOut: () => void }) {
  return (
    <div className="border-t border-hairline p-3">
      <div className="flex flex-col gap-0.5 px-2 pb-2">
        <span className="truncate text-body-sm font-medium text-ink" title={user.email}>
          {user.email}
        </span>
        <span className="text-body-sm text-ink-muted">{ROLE_LABELS[user.role]}</span>
      </div>
      <button
        type="button"
        onClick={onSignOut}
        className="flex w-full items-center gap-3 rounded-button px-3 py-2 text-body font-medium text-ink-secondary transition-colors hover:bg-surface hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <LogOut className="size-4 shrink-0" aria-hidden="true" />
        Sign out
      </button>
    </div>
  );
}

export function AppShell({ user, children }: { user: UserResponse; children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const items = NAV_BY_ROLE[user.role];

  // Nav information scent — only staff have dashboard:view; the shared "dashboard" SWR
  // key means this rides along with the dashboard page's fetch (no extra request).
  const isSchoolStaff = user.role === "school_admin" || user.role === "teacher";
  const { dashboard } = useDashboard(isSchoolStaff);
  // Student "new photos" badge (BP4) — its own signal, gated off for non-students.
  const { notifications } = useMyNotifications(user.role === "student");
  const navBadges: Record<string, NavBadge> = {};
  if (dashboard) {
    if (dashboard.students.failed > 0) {
      navBadges["/students"] = { count: dashboard.students.failed, tone: "error" };
    }
    if (dashboard.needs_attention.events_undistributed > 0) {
      navBadges["/events"] = {
        count: dashboard.needs_attention.events_undistributed,
        tone: "warning",
      };
    }
  }
  if (notifications && notifications.unseen_count > 0) {
    navBadges["/me/events"] = {
      count: notifications.unseen_count,
      tone: "accent",
      label: `${notifications.unseen_count} new`,
    };
  }

  // Close the mobile drawer if the viewport grows to desktop while it's open — otherwise
  // Radix keeps body scroll locked + focus trapped on a now-hidden (sm:hidden) panel.
  useEffect(() => {
    const mql = window.matchMedia("(min-width: 640px)");
    function onChange() {
      if (mql.matches) setDrawerOpen(false);
    }
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  async function handleLogout() {
    try {
      await logout();
    } catch {
      // Clear-and-go regardless; cookies are cleared server-side on success, and proxy.ts
      // bounces to /login if they weren't.
    }
    // Drop the cached user so nothing reads a stale session after logout.
    await mutate("auth/me", undefined, { revalidate: false });
    router.replace("/login");
    router.refresh();
  }

  return (
    <div className="flex min-h-dvh bg-surface">
      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-hairline bg-canvas sm:flex">
        <div className="flex h-14 items-center border-b border-hairline px-5">
          <span className="text-headline text-ink">Photos</span>
        </div>
        <NavList items={items} pathname={pathname} badges={navBadges} />
        <UserFooter user={user} onSignOut={handleLogout} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile header with a slide-in nav drawer */}
        <header className="flex h-14 items-center justify-between border-b border-hairline bg-canvas px-4 sm:hidden">
          <div className="flex items-center gap-2">
            <DialogPrimitive.Root open={drawerOpen} onOpenChange={setDrawerOpen}>
              <DialogPrimitive.Trigger asChild>
                <button
                  type="button"
                  aria-label="Open menu"
                  className="-ml-1 rounded-button p-1 text-ink-secondary transition-colors hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <Menu className="size-5" />
                </button>
              </DialogPrimitive.Trigger>
              <DialogPrimitive.Portal>
                <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-ink/50 sm:hidden" />
                <DialogPrimitive.Content className="fixed left-0 top-0 z-50 flex h-full w-64 flex-col border-r border-hairline bg-canvas focus:outline-none sm:hidden">
                  <DialogPrimitive.Title className="sr-only">Menu</DialogPrimitive.Title>
                  <DialogPrimitive.Description className="sr-only">
                    Navigate the app.
                  </DialogPrimitive.Description>
                  <div className="flex h-14 items-center justify-between border-b border-hairline px-5">
                    <span className="text-headline text-ink">Photos</span>
                    <DialogPrimitive.Close
                      aria-label="Close menu"
                      className="-mr-1 rounded-button p-1 text-ink-muted transition-colors hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <X className="size-5" />
                    </DialogPrimitive.Close>
                  </div>
                  <NavList
                    items={items}
                    pathname={pathname}
                    badges={navBadges}
                    onNavigate={() => setDrawerOpen(false)}
                  />
                  <UserFooter user={user} onSignOut={handleLogout} />
                </DialogPrimitive.Content>
              </DialogPrimitive.Portal>
            </DialogPrimitive.Root>
            <span className="text-headline text-ink">Photos</span>
          </div>
        </header>
        <main className="flex-1 p-4 sm:p-8">
          <div className="mx-auto w-full max-w-6xl">{children}</div>
        </main>
      </div>
    </div>
  );
}
