import { NextResponse } from "next/server";

import { type AuthResponse, BACKEND_ORIGIN } from "@/lib/auth/backend";
import { setAuthCookies } from "@/lib/auth/cookies";

/**
 * POST /api/auth/login — proxy credentials to the backend, then store the returned
 * tokens as HttpOnly cookies. Only `must_change_password` is returned to the
 * browser; the JWTs never leave the server (decisions/0031).
 */
export async function POST(request: Request): Promise<NextResponse> {
  const body = await request.text();

  let backendRes: Response;
  try {
    backendRes = await fetch(`${BACKEND_ORIGIN}/v1/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json" },
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
      { detail: data?.detail ?? "Login failed" },
      { status: backendRes.ok ? 502 : backendRes.status },
    );
  }

  const res = NextResponse.json(
    { must_change_password: Boolean(data.must_change_password) },
    { status: 200 },
  );
  setAuthCookies(res, data.access_token, data.refresh_token, data.expires_in ?? 900);
  return res;
}
