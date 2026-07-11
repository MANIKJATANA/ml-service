/**
 * Server-only helpers for the BFF → FastAPI backend calls (decisions/0031).
 * The browser never sees this origin or the JWTs.
 */

// Backend origin as seen from the Next server. Compose sets http://backend:8000.
// The host-dev fallback uses the IPv4 literal 127.0.0.1 (not "localhost"): Node's
// fetch resolves localhost to IPv6 ::1 first, which Docker Desktop's published port
// may refuse (ECONNREFUSED) even though curl's happy-eyeballs hides it.
export const BACKEND_ORIGIN = process.env.BFF_BACKEND_ORIGIN ?? "http://127.0.0.1:8001";

/** The backend's token response (POST /v1/auth/login and /v1/auth/refresh). */
export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  must_change_password: boolean;
}

/**
 * Exchange a refresh token for a fresh token pair. Returns null if the backend
 * rejects it (expired/disabled) or is unreachable — the caller then clears the
 * session and forces re-login.
 */
export async function refreshTokens(refreshToken: string): Promise<AuthResponse | null> {
  let res: Response;
  try {
    res = await fetch(`${BACKEND_ORIGIN}/v1/auth/refresh`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  } catch {
    return null;
  }
  if (!res.ok) return null;
  return (await res.json().catch(() => null)) as AuthResponse | null;
}
