import { type NextRequest, NextResponse } from "next/server";

import { type AuthResponse, BACKEND_ORIGIN } from "@/lib/auth/backend";
import { ACCESS_COOKIE, setAuthCookies } from "@/lib/auth/cookies";

/**
 * POST /api/auth/change-password — forward the change with the access-token Bearer.
 * The backend clears `must_change_password` AND (BP18d) re-issues a fresh token pair — its
 * token_version bump revoked the old one — which we store as the new cookies so the user isn't
 * logged out of their own session by their own password change.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const access = request.cookies.get(ACCESS_COOKIE)?.value;
  if (!access) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const body = await request.text();

  let backendRes: Response;
  try {
    backendRes = await fetch(`${BACKEND_ORIGIN}/v1/auth/change-password`, {
      method: "POST",
      headers: { "content-type": "application/json", Authorization: `Bearer ${access}` },
      body,
    });
  } catch {
    return NextResponse.json({ detail: "Auth service unreachable" }, { status: 502 });
  }

  const data = (await backendRes.json().catch(() => null)) as
    | (Partial<AuthResponse> & { detail?: string })
    | null;

  if (!backendRes.ok || !data?.access_token || !data.refresh_token) {
    return NextResponse.json(
      { detail: data?.detail ?? "Change password failed" },
      { status: backendRes.ok ? 502 : backendRes.status },
    );
  }

  // BP18d: swap in the re-issued tokens so the acting session survives the password change.
  const res = NextResponse.json(
    { must_change_password: Boolean(data.must_change_password) },
    { status: 200 },
  );
  setAuthCookies(res, data.access_token, data.refresh_token, data.expires_in ?? 900);
  return res;
}
