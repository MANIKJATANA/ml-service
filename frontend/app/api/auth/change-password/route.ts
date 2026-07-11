import { type NextRequest, NextResponse } from "next/server";

import { BACKEND_ORIGIN } from "@/lib/auth/backend";
import { ACCESS_COOKIE } from "@/lib/auth/cookies";

/**
 * POST /api/auth/change-password — forward the change with the access-token Bearer.
 * The backend clears `must_change_password`; the client then re-fetches /me.
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

  if (backendRes.status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  const data = await backendRes.json().catch(() => ({ detail: "Change password failed" }));
  return NextResponse.json(data, { status: backendRes.status });
}
