/**
 * The HTTP boundary.
 *
 * Every non-streaming request goes through `apiFetch`, which knows two things
 * so no caller has to: responses are wrapped in `{ data, meta }`, and a
 * non-2xx status is an error rather than a value.
 */

export interface ApiEnvelope<T> {
  data: T;
  meta: { status: string };
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/**
 * The request never produced an answer: no connection, no response in time,
 * or a body that was not what the server sends.
 *
 * Not an `ApiError` with a made-up status, and the difference matters: the
 * query client retries anything that is not a 4xx `ApiError`, and these are
 * exactly the failures worth a second try. Status 0 would read as a 4xx and
 * never be retried.
 */
export class NetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NetworkError';
  }
}

// Long enough for the slowest plain request this app makes — the CSV export of
// every patient — and short enough that a server which has stopped answering
// is reported rather than waited on forever. Streams are not plain requests;
// they have their own stall watchdog in `src/api/stream.ts`.
const REQUEST_TIMEOUT_MS = 30_000;

/**
 * What to say for an error response that carries no message of its own — a
 * proxy's 502 while the backend restarts, say.
 *
 * Not `response.statusText`: HTTP/2 has no reason phrase, so behind any
 * modern proxy it is the empty string, and the banner it fills is blank.
 */
function statusMessage(status: number): string {
  if ([502, 503, 504].includes(status)) {
    return 'The server is unavailable right now. Try again in a moment.';
  }
  if (status >= 500) return 'The server ran into a problem. Try again in a moment.';
  if (status === 404) return 'Not found.';
  return `The request failed (HTTP ${String(status)}).`;
}

/**
 * Turn whatever a failed `fetch` or body read threw into something to show —
 * except an abort the caller asked for, which is passed through untouched:
 * that is a component unmounting or a query being cancelled, not a failure,
 * and TanStack relies on seeing it as an abort.
 */
function asNetworkError(caught: unknown, callerSignal: AbortSignal | null | undefined): unknown {
  if (callerSignal?.aborted === true) return caught;
  if (caught instanceof DOMException && caught.name === 'TimeoutError') {
    return new NetworkError('The server took too long to respond. Try again in a moment.');
  }
  if (caught instanceof SyntaxError) {
    return new NetworkError("The server sent a response this app couldn't read.");
  }
  return new NetworkError("Couldn't reach the server. Check your connection and try again.");
}

/**
 * The human-readable message out of an error response.
 *
 * FastAPI puts it in `detail` — but only for `HTTPException`. A 422 from
 * request validation puts an *array* of per-field errors there instead, and a
 * failure from in front of the app (a proxy, a dead upstream) has no JSON at
 * all. Anything that is not a plain string falls back to a sentence chosen by
 * status, because `[object Object]` in an error banner is worse than a
 * generic one.
 */
export async function errorDetail(response: Response): Promise<string> {
  const body: unknown = await response.json().catch(() => null);
  const detail = (body as { detail?: unknown } | null)?.detail;
  return typeof detail === 'string' && detail !== '' ? detail : statusMessage(response.status);
}

/** A 403: signed in, or a visitor, but without the role this needs — as
 *  opposed to something that failed. The pages behind a role say so, rather
 *  than "could not load", which reads as broken. */
export function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403;
}

/**
 * The human-readable message out of a caught error, for an error banner.
 *
 * `ApiError` carries the server's own message, or `errorDetail`'s fallback,
 * and `NetworkError` one written for a person. Anything else is not
 * something this app threw, and gets a message that does not assume the shape
 * of whatever it was.
 */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof NetworkError) return error.message;
  if (error instanceof Error && error.message !== '') return error.message;
  return 'Something went wrong.';
}

/**
 * The raw response for a request that isn't a `{ data, meta }` envelope —
 * today, only the CSV export in `src/api/cohort.ts`. Everything else wants
 * `apiFetch`, which is this plus the envelope unwrap.
 */
export async function apiRequest(path: string, init?: RequestInit): Promise<Response> {
  // Built with `Headers` rather than object spread. `RequestInit['headers']`
  // is allowed to be a `Headers` instance or an array of [name, value] pairs
  // as well as a plain object, and spreading either of those into an object
  // literal silently yields nothing useful instead of headers. The caller's
  // headers win over the default content type.
  const headers = new Headers({ 'Content-Type': 'application/json' });
  new Headers(init?.headers).forEach((value, name) => headers.set(name, value));

  const timeout = AbortSignal.timeout(REQUEST_TIMEOUT_MS);
  const signal = init?.signal ? AbortSignal.any([init.signal, timeout]) : timeout;

  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, headers, signal });
  } catch (caught) {
    throw asNetworkError(caught, init?.signal);
  }

  if (!response.ok) {
    throw new ApiError(await errorDetail(response), response.status);
  }

  return response;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiRequest(path, init);
  // The body is read under the same timeout as the request, and can fail the
  // same ways — plus one more: a 200 that is not JSON, which is what an
  // address the proxy does not route to the API returns (the app's own HTML).
  try {
    const envelope = (await response.json()) as ApiEnvelope<T>;
    return envelope.data;
  } catch (caught) {
    throw asNetworkError(caught, init?.signal);
  }
}
