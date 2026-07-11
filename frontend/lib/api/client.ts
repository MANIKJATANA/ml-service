import { ApiError } from "./errors";

/**
 * Fetch a same-origin BFF route (`/api/**`). The browser only ever talks to the
 * Next app; the route handlers attach the JWT from the HttpOnly cookie and proxy
 * to FastAPI (decisions/0030). Throws {@link ApiError} (status + `detail`) on a
 * non-2xx response; returns `undefined` for 204.
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
    const detail =
      body && typeof body === "object" && "detail" in body && typeof body.detail === "string"
        ? body.detail
        : res.statusText || "Request failed";
    throw new ApiError(res.status, detail);
  }

  return body as T;
}
