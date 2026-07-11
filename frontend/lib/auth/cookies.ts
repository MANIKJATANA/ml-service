import type { NextResponse } from "next/server";

/** Names of the HttpOnly auth cookies the BFF manages (decisions/0031). */
export const ACCESS_COOKIE = "access";
export const REFRESH_COOKIE = "refresh";

// Refresh-token lifetime — mirrors the backend BE_REFRESH_TOKEN_TTL_S default (14 days).
const REFRESH_MAX_AGE_S = 60 * 60 * 24 * 14;

// Secure cookies aren't sent over http://localhost, so only require Secure in prod.
const isProd = process.env.NODE_ENV === "production";

function cookieOptions(maxAgeS: number) {
  return {
    httpOnly: true as const,
    secure: isProd,
    sameSite: "lax" as const,
    path: "/",
    maxAge: maxAgeS,
  };
}

/** Set the access + refresh HttpOnly cookies on a response. */
export function setAuthCookies(
  res: NextResponse,
  accessToken: string,
  refreshToken: string,
  accessMaxAgeS: number,
): void {
  res.cookies.set(ACCESS_COOKIE, accessToken, cookieOptions(accessMaxAgeS));
  res.cookies.set(REFRESH_COOKIE, refreshToken, cookieOptions(REFRESH_MAX_AGE_S));
}

/** Expire both auth cookies (logout, or an unrecoverable 401). */
export function clearAuthCookies(res: NextResponse): void {
  res.cookies.set(ACCESS_COOKIE, "", cookieOptions(0));
  res.cookies.set(REFRESH_COOKIE, "", cookieOptions(0));
}
