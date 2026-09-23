/**
 * SSE consumption.
 *
 * WHY NOT `EventSource`: it cannot set headers, so the moment this app has auth
 * it is unusable — and it gives you no way to abort cleanly. `fetch` +
 * `ReadableStream` gives headers, `AbortSignal`, and the same frame parsing,
 * which is the twenty lines below.
 *
 * WHAT CHANGED WITH THE WORKER: this used to be the response to sending a
 * message, so it existed once per turn and died with it. Now it is a *view onto
 * a conversation* that can be opened at any time, from any point, by anyone
 * watching — including a tab that refreshed halfway through an answer. `since`
 * is the whole interface: "I have seen up to here."
 *
 * Mirrors the frames published in backend/app/worker.py and forwarded by the
 * stream endpoint in backend/app/api/routes/conversations.py.
 */

import { authHeaders } from 'src/api/auth';
import { ApiError, errorDetail } from 'src/api/client';
import type { ConversationEvent, TaskStatus } from 'src/api/conversations';

export type StreamFrame =
  /** A durable row. Identical to what the REST endpoint returns, so one folding
   *  function handles both. */
  | { type: 'event'; event: ConversationEvent }
  /** Where the turn stands. A terminal status means the stream is over. */
  | { type: 'status'; taskId: string | null; status: 'idle' | TaskStatus; error?: null | string }
  /** Live tokens. Never stored, and replaced by the `assistant_message` event
   *  that follows — so dropping one costs a flicker, not correctness. */
  | { type: 'text'; text: string }
  | { type: 'thinking'; text: string };

// Three missed keep-alives. See `expectMoreWithin` below.
const STALL_MS = 45_000;

export const TERMINAL_STATUSES = new Set([
  'cancelled',
  'failed',
  'idle',
  'succeeded',
  'superseded',
]);

interface OpenStreamOptions {
  conversationId: string;
  onFrame: (frame: StreamFrame) => void;
  signal?: AbortSignal;
  /** Highest event seq already displayed. Everything after it is replayed. */
  since: number;
}

export async function openConversationStream({
  conversationId,
  onFrame,
  signal,
  since,
}: OpenStreamOptions): Promise<void> {
  // The header is why this is `fetch` and not `EventSource`: EventSource cannot
  // set one, which makes it unusable for any authenticated stream. That was
  // true before there was any auth to speak of, and it is why turning auth on
  // did not require rewriting this.
  const response = await fetch(`/api/conversations/${conversationId}/stream?since=${since}`, {
    headers: await authHeaders(),
    signal,
  });

  // A failure BEFORE the stream opens is a normal HTTP error, and it is thrown
  // as one — with its status, because the caller does opposite things with a
  // 404 (stop: there is nothing to watch) and a 502 (back off and try again:
  // the server is on its way back). A failure AFTER the stream opens cannot be
  // a status code, so it arrives as a failed `status` frame instead.
  //
  // This used to report the first kind as a failed frame too, with no task id.
  // The caller could not tell it from a turn that failed, and reattached at
  // once — which, for as long as the backend was down, was a tight loop from
  // every open tab.
  if (!response.ok || !response.body) {
    throw new ApiError(await errorDetail(response), response.status);
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();

  // The server sends a keep-alive after HEARTBEAT_SECONDS (15) of quiet — see
  // the stream endpoint in backend/app/api/routes/conversations.py. Three
  // missed in a row is a connection that died without closing, which a proxy
  // whose upstream vanished will happily do forever. Cancelling the read ends
  // it, and it is then handled like any other early end, below.
  let watchdog: ReturnType<typeof setTimeout> | undefined;
  const expectMoreWithin = () => {
    clearTimeout(watchdog);
    watchdog = setTimeout(() => void reader.cancel(), STALL_MS);
  };

  // Whether the server said the stream was over — a terminal status, "idle"
  // included. A stream can also simply end: a backend restarting closes its
  // connections cleanly, and a proxy can close a quiet one. That is a dropped
  // connection, not a finished turn, and returning as if it were one left the
  // page showing Stop forever with nothing reconnecting.
  let isOver = false;
  let buffer = '';

  expectMoreWithin();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      expectMoreWithin();

      buffer += value;

      // Frames are delimited by a blank line. A chunk can split a frame anywhere,
      // including mid-character, so we accumulate and only consume whole frames.
      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);

        // Lines starting with ':' are comments — the keep-alive the server sends
        // on a quiet stream. Skipping them is the entire handling required.
        const dataLine = frame.split('\n').find((line) => line.startsWith('data:'));
        if (dataLine) {
          const parsed = JSON.parse(dataLine.slice(5).trim()) as StreamFrame;
          if (parsed.type === 'status' && TERMINAL_STATUSES.has(parsed.status)) isOver = true;
          onFrame(parsed);
        }

        boundary = buffer.indexOf('\n\n');
      }
    }
  } finally {
    clearTimeout(watchdog);
  }

  if (!isOver && signal?.aborted !== true) {
    throw new Error('The connection to the server dropped before the answer finished.');
  }
}
