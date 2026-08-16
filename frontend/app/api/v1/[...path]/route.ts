import { type NextRequest, NextResponse } from "next/server";

import { BACKEND_ORIGIN, refreshTokens } from "@/lib/auth/backend";
import {
  ACCESS_COOKIE,
  clearAuthCookies,
  REFRESH_COOKIE,
  setAuthCookies,
} from "@/lib/auth/cookies";

/**
 * Transparent authenticated proxy: the browser calls same-origin `/api/v1/<path>`,
 * this attaches the access token from the HttpOnly cookie and forwards to
 * `${BACKEND}/v1/<path>`. On a 401 it refreshes once (rotating the cookies) and
 * retries; on an unrecoverable 401 it clears the session (decisions/0031).
 */

function callBackend(
  req: NextRequest,
  path: string,
  accessToken: string | undefined,
  body: string | undefined,
): Promise<Response> {
  const headers = new Headers();
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);

  return fetch(`${BACKEND_ORIGIN}/v1/${path}${req.nextUrl.search}`, {
    method: req.method,
    headers,
    body,
    redirect: "manual",
  });
}

async function proxy(req: NextRequest, path: string): Promise<NextResponse> {
  const method = req.method.toUpperCase();
  const body = method === "GET" || method === "HEAD" ? undefined : await req.text();

  const access = req.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = req.cookies.get(REFRESH_COOKIE)?.value;

  let backendRes: Response;
  let rotated: Awaited<ReturnType<typeof refreshTokens>> = null;
  try {
    backendRes = await callBackend(req, path, access, body);

    if (backendRes.status === 401 && refresh) {
      rotated = await refreshTokens(refresh);
      if (rotated?.access_token && rotated.refresh_token) {
        backendRes = await callBackend(req, path, rotated.access_token, body);
      } else {
        // A malformed/failed refresh is unrecoverable — fall through to clearing.
        rotated = null;
      }
    }
  } catch {
    // Backend unreachable — return a clean 502 (not an unhandled 500).
    return NextResponse.json({ detail: "Service unavailable" }, { status: 502 });
  }

  const resBody = await backendRes.text();
  // Forward content-type + Retry-After (BP8c's 429 throttle) so the client can humanize a
  // rate-limit response ("try again in N seconds") instead of reading it as a generic error.
  const outHeaders: Record<string, string> = {};
  const contentType = backendRes.headers.get("content-type");
  if (contentType) outHeaders["content-type"] = contentType;
  const retryAfter = backendRes.headers.get("retry-after");
  if (retryAfter) outHeaders["retry-after"] = retryAfter;
  const out = new NextResponse(resBody || null, {
    status: backendRes.status,
    headers: Object.keys(outHeaders).length > 0 ? outHeaders : undefined,
  });

  if (rotated?.access_token && rotated.refresh_token) {
    setAuthCookies(out, rotated.access_token, rotated.refresh_token, rotated.expires_in ?? 900);
  } else if (backendRes.status === 401) {
    // Couldn't authenticate (no/failed refresh) → drop the session so the next
    // navigation is bounced to /login by proxy.ts. (403 does NOT clear — it's a
    // valid session lacking permission.)
    clearAuthCookies(out);
  }
  return out;
}

async function handler(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  const { path } = await ctx.params;
  return proxy(req, path.join("/"));
}

export {
  handler as DELETE,
  handler as GET,
  handler as PATCH,
  handler as POST,
  handler as PUT,
};
