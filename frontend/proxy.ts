import { type NextRequest, NextResponse } from "next/server";

import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth/cookies";

/**
 * Optimistic auth gate (decisions/0031). Per the Next 16 docs, `proxy.ts` only
 * does a cheap cookie-PRESENCE check — no network, no token decode. Real authz is
 * the backend's job (RBAC → 403); role/must-change routing happens in the shell.
 */

// Routes reachable WITHOUT a session. Everything else requires one.
// (/change-password needs a session — it's not listed here.)
const PUBLIC_PATHS = ["/login"];

function isPublic(pathname: string): boolean {
  return PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export function proxy(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;
  const hasSession =
    Boolean(request.cookies.get(ACCESS_COOKIE)?.value) ||
    Boolean(request.cookies.get(REFRESH_COOKIE)?.value);

  if (!hasSession && !isPublic(pathname)) {
    return NextResponse.redirect(new URL("/login", request.nextUrl));
  }
  if (hasSession && pathname === "/login") {
    return NextResponse.redirect(new URL("/", request.nextUrl));
  }
  return NextResponse.next();
}

export const config = {
  // Skip the BFF (/api gates itself), Next internals, and any static file (paths
  // with a dot: favicon.ico, robots.txt, images in /public, …) so they don't get
  // bounced to /login.
  matcher: ["/((?!api|_next/static|_next/image|.*\\..*).*)"],
};
