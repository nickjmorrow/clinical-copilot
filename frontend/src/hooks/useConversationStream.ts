import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from 'src/api/client';
import {
  cancelTurn,
  type Conversation,
  type ConversationDetail,
  type ConversationEvent,
  conversationKeys,
  createConversation,
  getConversation,
  mergeEvents,
  sendMessage,
  type SendMessageReceipt,
} from 'src/api/conversations';
import { openConversationStream, type StreamFrame, TERMINAL_STATUSES } from 'src/api/stream';
import { describeTurnError } from 'src/format';

const lastSeq = (events: ConversationEvent[]) =>
  events.reduce((highest, event) => Math.max(highest, event.seq), 0);

/** What sending produced. `created` is non-null only for a draft's first message. */
interface StartedTurn {
  conversationId: string;
  created: Conversation | null;
  receipt: SendMessageReceipt;
}

export interface ConversationStream {
  error: null | string;
  events: ConversationEvent[];
  /** An existing conversation whose transcript has not arrived yet — which
   *  must not render as the empty draft it would otherwise look like. */
  isLoading: boolean;
  isStreaming: boolean;
  liveText: string;
  /**
   * The conversation could not be fetched at all. Only while nothing has
   * loaded: a background refetch failing under a transcript already on
   * screen is not a reason to take the transcript away.
   */
  loadError: Error | null;
  retryLoad: () => void;
  send: (content: string) => void;
  stop: () => void;
  thinkingText: string;
}

/**
 * Watching and driving one conversation — including one that does not exist yet.
 *
 * The important property is that **watching is not tied to sending.** This
 * opens a stream whenever the server says a turn is in flight — after you
 * send, or the moment the page loads onto a conversation that was already
 * generating. Refreshing mid-answer is therefore not a case anyone had to
 * handle; it is the ordinary path with a different starting cursor.
 *
 * **Sending is allowed while a turn is running**, and needs no special case
 * here for the same reason: the server supersedes the old task and the receipt
 * names a new cursor, so the second message takes exactly the path the first
 * one did. The only extra work is closing the stream that was watching the turn
 * it replaced, which `onSuccess` does before anything else.
 *
 * Three pieces of state, and the split matters:
 *   - the fetched transcript (TanStack Query, server state)
 *   - events that arrived over the stream (local, merged by `seq`)
 *   - live tokens (local, ephemeral, replaced by the durable event that follows)
 *
 * It is a hook rather than part of the component because none of that is
 * layout. `Chat` renders a list and a composer; everything about cursors,
 * reattaching and supersession lives here, where it can be read in one piece.
 *
 * **A null `conversationId` is a draft**, and sending is what creates it. That
 * belongs here rather than in `ChatPage` because it is the same sentence as sending:
 * the id is a detail of how the message gets written down, not a thing the
 * layout above has to sequence. See CONVENTIONS.md > Starting one.
 *
 * **Assumes it is remounted when `conversationId` changes.** `ChatPage` passes
 * `key={id ?? 'new'}` to `Chat` for exactly that reason, which is React's own
 * answer to "reset all state when a prop changes" and is why there is no effect
 * here clearing six things by hand.
 */
export default function useConversationStream(
  conversationId: null | string,
  onCreated: (id: string) => void,
): ConversationStream {
  const queryClient = useQueryClient();

  const {
    data: conversation,
    error: loadError,
    refetch,
  } = useQuery({
    // A draft has nothing to fetch. The null branch in `queryFn` is there
    // because the id in the closure is nullable; `enabled` is what stops it.
    enabled: conversationId !== null,
    queryFn: () => (conversationId === null ? null : getConversation(conversationId)),
    queryKey: conversationKeys.detail(conversationId ?? 'draft'),
  });

  const [streamedEvents, setStreamedEvents] = useState<ConversationEvent[]>([]);
  const [liveText, setLiveText] = useState('');
  const [thinkingText, setThinkingText] = useState('');
  const [error, setError] = useState<null | string>(null);

  // Non-null while a stream should be open, and its value is where to resume
  // from. Setting it opens a stream; clearing it closes one.
  const [resumeFrom, setResumeFrom] = useState<null | number>(null);

  // Guards the one loop this design allows: a turn ends, we stop streaming, but
  // the refetch has not landed yet and still reports that task as active — so
  // we would reattach to a task we just watched finish.
  const settledTaskRef = useRef<null | string>(null);

  // The task the open stream is watching, as far as this browser knows. Needed
  // for the frames that do not name one: an "idle" from the server, or a
  // refusal to open, both mean "stop watching *that* task" — and recording it
  // as settled is what stops the reattach effect reopening the stream while
  // the refetch that will clear it is still in flight.
  const resumingTaskRef = useRef<null | string>(null);

  // The open stream, so that sending can close it *synchronously*.
  //
  // The effect below already aborts on a dep change, but that runs after the
  // render the state update schedules, and the read loop is a live async
  // iteration — it can deliver another chunk in between. Those chunks belong to
  // the turn that was just superseded, and the tokens among them carry no task
  // id to filter on, so they would land in `liveText` as text the server has
  // already decided to throw away. Aborting first closes that window instead of
  // narrowing it.
  const streamRef = useRef<AbortController | null>(null);

  // Consecutive failed attempts to open the stream, for backing off between
  // them. Reset by the first frame a stream delivers.
  const failuresRef = useRef(0);

  // What a draft's create produced, kept so a retry cannot produce a second
  // one. The window is small — create succeeded, the send after it failed, the
  // user tries again — and the alternative is exactly the blank conversation
  // the draft exists to stop leaving behind.
  const draftRef = useRef<Conversation | null>(null);

  const events = mergeEvents(conversation?.events ?? [], streamedEvents);

  const handleFrame = useCallback(
    (frame: StreamFrame) => {
      switch (frame.type) {
        case 'event': {
          setStreamedEvents((previous) => [...previous, frame.event]);
          // The authoritative text has landed; drop the token-by-token preview
          // it replaces. This is also what heals a dropped delta.
          if (frame.event.type === 'assistant_message') setLiveText('');
          setThinkingText((previous) => (previous ? '' : previous));
          break;
        }

        case 'status': {
          // The server has no turn running for this conversation — it
          // finished while we were not watching, or it never started. Stop
          // streaming, and refetch so the cached `activeTask` catches up.
          if (frame.status === 'idle') {
            settledTaskRef.current = resumingTaskRef.current;
            setResumeFrom(null);
            setLiveText('');
            setThinkingText('');
            void queryClient.invalidateQueries({
              queryKey: conversationKeys.detail(conversationId ?? 'draft'),
            });
            break;
          }
          if (frame.status === 'failed' && frame.error) setError(describeTurnError(frame.error));
          if (TERMINAL_STATUSES.has(frame.status)) {
            settledTaskRef.current = frame.taskId;
            setResumeFrom(null);
            setLiveText('');
            setThinkingText('');
            void queryClient.invalidateQueries({
              queryKey: conversationKeys.detail(conversationId ?? 'draft'),
            });
            void queryClient.invalidateQueries({ queryKey: conversationKeys.all });
          }
          break;
        }

        case 'text': {
          setLiveText((previous) => previous + frame.text);
          setThinkingText((previous) => (previous ? '' : previous));
          break;
        }

        case 'thinking': {
          setThinkingText((previous) => previous + frame.text);
          break;
        }
      }
    },
    [conversationId, queryClient],
  );

  // Reattach on load. The server told us a task is still running, so pick the
  // stream up from the end of what we were given.
  useEffect(() => {
    if (!conversation?.activeTask || resumeFrom !== null) return;
    if (conversation.activeTask.id === settledTaskRef.current) return;
    resumingTaskRef.current = conversation.activeTask.id;
    setResumeFrom(lastSeq(conversation.events));
  }, [conversation, resumeFrom]);

  // The stream itself. Abort on unmount or conversation change — the work keeps
  // running in the worker either way, which is the entire point.
  useEffect(() => {
    if (resumeFrom === null || conversationId === null) return;

    const controller = new AbortController();
    streamRef.current = controller;
    let retry: ReturnType<typeof setTimeout> | undefined;
    void (async () => {
      try {
        await openConversationStream({
          conversationId,
          onFrame: (frame) => {
            if (failuresRef.current > 0) {
              failuresRef.current = 0;
              setError(null);
            }
            handleFrame(frame);
          },
          signal: controller.signal,
          since: resumeFrom,
        });
      } catch (caught) {
        // Our own abort, whatever shape the error it surfaced as. Checking the
        // error's type is not enough: an abort can reject a read through the
        // decoder stream with something other than an AbortError, and that
        // used to fall through to the retry below — scheduling a timer after
        // this effect's cleanup had already run, so nothing ever cleared it,
        // and it reopened a stream this effect had deliberately closed.
        if (controller.signal.aborted) return;

        // Refused outright — the conversation is gone, or not yours. Nothing
        // will change on a retry, so say so and stop watching.
        if (caught instanceof ApiError && caught.status < 500) {
          settledTaskRef.current = resumingTaskRef.current;
          setError(caught.message);
          setResumeFrom(null);
          return;
        }

        // Backed off before clearing `resumeFrom`, because clearing it is what
        // reopens the stream: the reattach effect sees the task still running
        // and resumes at once. Immediately, that was a tight loop — tens of
        // thousands of requests a minute from every open tab for as long as
        // the backend was down, all landing together when it came back.
        // 1s, doubling, capped at 30s.
        const delay = Math.min(1000 * 2 ** failuresRef.current, 30_000);
        failuresRef.current += 1;
        setError('Lost the connection to the server. Reconnecting…');
        retry = setTimeout(() => {
          setResumeFrom(null);
        }, delay);
      }
    })();

    return () => {
      controller.abort();
      clearTimeout(retry);
    };
  }, [conversationId, handleFrame, resumeFrom]);

  const sendMutation = useMutation({
    mutationFn: async (content: string): Promise<StartedTurn> => {
      if (conversationId !== null) {
        return {
          conversationId,
          created: null,
          receipt: await sendMessage(conversationId, content),
        };
      }

      // The draft. Two requests rather than one because the second is the
      // ordinary send path — the conversation stops being special the instant
      // it has an id, and a create-with-message endpoint would be a second way
      // to write a user message that has to stay in step with the first.
      const created = draftRef.current ?? (await createConversation());
      draftRef.current = created;
      return {
        conversationId: created.id,
        created,
        receipt: await sendMessage(created.id, content),
      };
    },
    onError: (caught) =>
      setError(caught instanceof Error ? caught.message : 'Could not send that.'),
    onSuccess: ({ conversationId: id, created, receipt }) => {
      settledTaskRef.current = null;

      // This message may have superseded a turn that was still generating. The
      // server has already retired that task and discarded whatever it had
      // written — a superseded turn is not a shorter turn, because the message
      // that replaced it now sits after it in the log — so the preview on
      // screen is text that will never become a row. Close the stream carrying
      // it and drop it, in that order, or its last few tokens arrive after the
      // clear and sit there permanently.
      streamRef.current?.abort();
      setLiveText('');
      setThinkingText('');

      if (created === null) {
        // Resume from the message we just wrote: we already have it, and we
        // want everything after it.
        resumingTaskRef.current = receipt.taskId;
        setResumeFrom(receipt.seq);
        void queryClient.invalidateQueries({ queryKey: conversationKeys.detail(id) });
        return;
      }

      // A draft just became real, which means `ChatPage` is about to re-key `Chat`
      // and this instance is about to be unmounted. So the handover is written
      // into the cache the remounted one will read, rather than into state that
      // is about to be thrown away.
      //
      // `events` is left empty on purpose: the reattach below resumes from 0
      // and the stream replays the message that was just written, so nothing
      // here has to guess at the shape of a row the server already has. The
      // task is the part worth seeding — without it the composer flickers back
      // out of "Stop" for a round trip.
      queryClient.setQueryData<ConversationDetail>(conversationKeys.detail(id), {
        ...created,
        activeTask: {
          createdAt: new Date().toISOString(),
          id: receipt.taskId,
          kind: 'chat_turn',
          status: 'pending',
        },
        events: [],
      });
      queryClient.setQueryData<Conversation[]>(conversationKeys.all, (existing) => [
        created,
        ...(existing ?? []),
      ]);
      void queryClient.invalidateQueries({ queryKey: conversationKeys.all });

      onCreated(id);
    },
  });

  const stopMutation = useMutation({
    // A draft can be mid-create, in which case there is no turn to stop yet and
    // nothing to address the request to.
    mutationFn: () =>
      conversationId === null ? Promise.resolve(null) : cancelTurn(conversationId),
  });

  const send = useCallback(
    (content: string) => {
      setError(null);
      sendMutation.mutate(content);
    },
    [sendMutation],
  );

  const stop = useCallback(() => stopMutation.mutate(), [stopMutation]);

  return {
    error,
    events,
    isLoading: conversationId !== null && conversation === undefined && loadError === null,
    isStreaming: resumeFrom !== null || sendMutation.isPending,
    liveText,
    loadError: conversation ? null : loadError,
    retryLoad: useCallback(() => void refetch(), [refetch]),
    send,
    stop,
    thinkingText,
  };
}
