import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiFetch, errorDetail, errorMessage, NetworkError } from 'src/api/client';

// What a person reads when a request fails. Every one of these used to reach
// the screen as something else: the browser's "Failed to fetch", a JSON parse
// error, or — behind an HTTP/2 proxy, whose responses have no status text —
// an empty banner.

const respond = (body: BodyInit | null, status: number) => new Response(body, { status });

/** A fetch that never answers, and rejects the way a real one does when its
 *  signal aborts — including a signal that was aborted before it was called. */
const hangingFetch = (_: string, init: RequestInit) =>
  new Promise((_resolve, reject) => {
    const signal = init.signal;
    const fail = () => {
      reject(signal?.reason as Error);
    };
    if (signal?.aborted === true) fail();
    else signal?.addEventListener('abort', fail);
  });

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('errorDetail', () => {
  it("uses the server's own message when there is one", async () => {
    const response = respond(JSON.stringify({ detail: 'Slow down.' }), 429);
    expect(await errorDetail(response)).toBe('Slow down.');
  });

  it('says the server is unavailable for a bare 502', async () => {
    expect(await errorDetail(respond('<html>Bad Gateway</html>', 502))).toMatch(/unavailable/);
  });

  it('never returns an empty message, whatever the body', async () => {
    // A 422's `detail` is an array of field errors, not a sentence.
    const body = JSON.stringify({ detail: [] });
    for (const status of [400, 404, 422, 500, 503]) {
      expect(await errorDetail(respond(body, status))).not.toBe('');
    }
  });
});

describe('apiFetch', () => {
  it('turns a dropped connection into a sentence, not "Failed to fetch"', async () => {
    vi.stubGlobal('fetch', () => Promise.reject(new TypeError('Failed to fetch')));

    const caught: unknown = await apiFetch('/anything').catch((caught_: unknown) => caught_);

    expect(caught).toBeInstanceOf(NetworkError);
    expect(errorMessage(caught)).toMatch(/Couldn't reach the server/);
  });

  it('reports a 200 that is not JSON as unreadable', async () => {
    vi.stubGlobal('fetch', () => Promise.resolve(respond('<!doctype html>', 200)));

    const caught: unknown = await apiFetch('/anything').catch((caught_: unknown) => caught_);

    expect(caught).toBeInstanceOf(NetworkError);
    expect(errorMessage(caught)).toMatch(/couldn't read/);
  });

  it('gives up on a server that never answers', async () => {
    // Standing in for the 30 seconds: Node's timeout signal does not run on
    // vitest's fake clock, so the test fires it by hand, exactly as it fires.
    const clock = new AbortController();
    vi.spyOn(AbortSignal, 'timeout').mockReturnValue(clock.signal);
    vi.stubGlobal('fetch', hangingFetch);

    const pending = apiFetch('/anything').catch((caught: unknown) => caught);
    clock.abort(new DOMException('signal timed out', 'TimeoutError'));

    expect(errorMessage(await pending)).toMatch(/took too long/);
  });

  it("passes the caller's own abort through untouched", async () => {
    const controller = new AbortController();
    vi.stubGlobal('fetch', hangingFetch);

    const pending = apiFetch('/anything', { signal: controller.signal }).catch(
      (caught_: unknown) => caught_,
    );
    controller.abort();

    const caught = await pending;
    expect(caught).toBeInstanceOf(DOMException);
    expect((caught as DOMException).name).toBe('AbortError');
  });

  it('throws an ApiError carrying the status for an error response', async () => {
    vi.stubGlobal('fetch', () => Promise.resolve(respond(JSON.stringify({ detail: 'No.' }), 403)));

    const caught: unknown = await apiFetch('/anything').catch((caught_: unknown) => caught_);

    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(403);
  });
});
