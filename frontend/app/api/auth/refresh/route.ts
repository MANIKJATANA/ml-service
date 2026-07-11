import { type NextRequest, NextResponse } from "next/server";

import { refreshTokens } from "@/lib/auth/backend";
import { clearAuthCookies, REFRESH_COOKIE, setAuthCookies } from "@/lib/auth/cookies";

/**
 * POST /api/auth/refresh — rotate the token pair from the refresh cookie. Mostly
 * the `/api/v1` proxy refreshes transparently; this is the explicit endpoint.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;
  if (!refresh) {
    const res = NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    clearAuthCookies(res);
    return res;
  }

  const tokens = await refreshTokens(refresh);
  if (!tokens?.access_token || !tokens.refresh_token) {
    const res = NextResponse.json({ detail: "Session expired" }, { status: 401 });
    clearAuthCookies(res);
    return res;
  }

  const res = NextResponse.json({ ok: true }, { status: 200 });
  setAuthCookies(res, tokens.access_token, tokens.refresh_token, tokens.expires_in ?? 900);
  return res;
}
