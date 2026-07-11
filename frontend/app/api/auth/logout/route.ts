import { NextResponse } from "next/server";

import { clearAuthCookies } from "@/lib/auth/cookies";

/** POST /api/auth/logout — clear the auth cookies. */
export async function POST(): Promise<NextResponse> {
  const res = new NextResponse(null, { status: 204 });
  clearAuthCookies(res);
  return res;
}
