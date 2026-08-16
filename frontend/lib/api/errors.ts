/** A failed API call: carries the HTTP status + a user-ready message. For a 429 the
 *  `retryAfter` seconds (from the `Retry-After` header) are also kept for programmatic use;
 *  `bffFetch` already folds them into the message (decisions/0074). */
export class ApiError extends Error {
  readonly status: number;
  readonly retryAfter?: number;

  constructor(status: number, detail: string, retryAfter?: number) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

export function isApiError(err: unknown): err is ApiError {
  return err instanceof ApiError;
}
