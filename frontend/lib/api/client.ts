import { ApiError } from "./errors";

/**
 * Fetch a same-origin BFF route (`/api/**`). The browser only ever talks to the
 * Next app; the route handlers attach the JWT from the HttpOnly cookie and proxy
 * to FastAPI (decisions/0030). Throws {@link ApiError} (status + a user-ready
 * message) on a non-2xx response; returns `undefined` for 204.
 */
export async function bffFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: {
      // Only advertise a JSON body when there actually is one (avoids sending
      // Content-Type: application/json on bodyless POSTs like logout).
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (res.status === 204) {
    return undefined as T;
  }

  const isJson = res.headers.get("content-type")?.includes("application/json") ?? false;
  const body: unknown = isJson ? await res.json() : null;

  if (!res.ok) {
    const retryAfter = parseRetryAfter(res.headers.get("retry-after"));
    throw new ApiError(res.status, errorMessage(res.status, body, res.statusText, retryAfter), retryAfter);
  }

  return body as T;
}

/** Turn a non-2xx response into a message a user can act on (decisions/0074, BP21b):
 *  a 5xx is generic (never the raw exception), a 429 is humanized with the Retry-After
 *  seconds, a 422 parses FastAPI's field-error array, everything else uses the backend
 *  `detail` string (401/403/404/409 messages are actionable). */
function errorMessage(
  status: number,
  body: unknown,
  statusText: string,
  retryAfter: number | undefined,
): string {
  if (status >= 500) {
    return "Something went wrong on our end — please try again in a moment.";
  }
  if (status === 429) {
    return retryAfter && retryAfter > 0
      ? `Too many requests — please try again in ${formatRetryAfter(retryAfter)}.`
      : "Too many requests — please try again in a moment.";
  }
  const detail = body && typeof body === "object" && "detail" in body ? body.detail : undefined;
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    // FastAPI 422 request-validation error: detail is [{loc, msg, type}, …].
    return parseValidationDetail(detail);
  }
  return statusText || "Request failed";
}

/** Build a readable message from a FastAPI 422 `detail` array, e.g.
 *  `[{loc:["body","email"], msg:"value is not a valid email address"}]`
 *  → "Email: value is not a valid email address". */
function parseValidationDetail(items: unknown[]): string {
  const msgs: string[] = [];
  for (const item of items) {
    if (!item || typeof item !== "object") continue;
    const rec = item as Record<string, unknown>;
    const msg = typeof rec.msg === "string" ? rec.msg : "invalid value";
    const field = fieldFromLoc(rec.loc);
    msgs.push(field ? `${field}: ${msg}` : msg);
  }
  if (msgs.length === 0) return "Please check the details and try again.";
  // Keep the toast short; note if more were collapsed.
  return msgs.length > 3 ? `${msgs.slice(0, 3).join("; ")}; …` : msgs.join("; ");
}

/** The human field name from a pydantic `loc` (drop the leading body/query/path segment,
 *  take the last field, snake_case → "Sentence case"). */
function fieldFromLoc(loc: unknown): string | null {
  if (!Array.isArray(loc)) return null;
  const parts = loc.filter(
    (p): p is string => typeof p === "string" && !["body", "query", "path"].includes(p),
  );
  const last = parts[parts.length - 1];
  if (!last) return null;
  const spaced = last.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Retry-After (BP8c sends integer seconds); undefined if absent or non-numeric.
 *  Note: the RFC-7231 HTTP-date form isn't parsed — it degrades to the "in a moment"
 *  fallback (BP8c never sends a date), see decisions/0074. */
function parseRetryAfter(header: string | null): number | undefined {
  if (!header) return undefined;
  const seconds = Number.parseInt(header, 10);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : undefined;
}

/** A wait as a clean phrase: exact seconds under a minute, rounded-up minutes beyond
 *  (so "in 3600 seconds" reads "in 60 minutes"). BP8c's short windows make ≥60s rare. */
function formatRetryAfter(seconds: number): string {
  if (seconds < 60) return `${seconds} second${seconds === 1 ? "" : "s"}`;
  const minutes = Math.ceil(seconds / 60);
  return `${minutes} minute${minutes === 1 ? "" : "s"}`;
}
