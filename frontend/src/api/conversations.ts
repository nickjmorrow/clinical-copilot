import { apiFetch } from 'src/api/client';

export interface Conversation {
  id: string;
  title: string | null;
  /** Non-null means pinned, and the value is where it sorts among the pinned. */
  pinnedAt: string | null;
  /** Non-null means it is in the archive rather than the list. */
  archivedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

/** A patch. An absent key means "leave it alone" — see the PATCH route. */
export interface ConversationPatch {
  archived?: boolean;
  pinned?: boolean;
  title?: string;
}

export type TaskStatus =
  'cancelled' | 'failed' | 'pending' | 'running' | 'succeeded' | 'superseded';

export interface Task {
  id: string;
  kind: 'agent_run' | 'chat_turn';
  status: TaskStatus;
  createdAt: string;
}

/**
 * One row of the transcript, mirroring the discriminated union in
 * backend/app/api/schemas.py.
 *
 * This is the *display* view of the event log. The model's view is built
 * separately by `load_history` on the backend and is deliberately not the same
 * shape — that freedom is the whole reason the transcript is stored as events.
 *
 * `seq` is the resume cursor: hand the highest one you have to the streaming
 * endpoint and it sends you everything after it. It is why a refresh mid-answer
 * costs nothing.
 *
 * (`type` values stay snake_case: they are data, not field names, and matching
 * the stored value keeps the two ends greppable together.)
 */
export type ConversationEvent =
  | { type: 'user_message'; id: string; seq: number; createdAt: string; text: string }
  | { type: 'assistant_message'; id: string; seq: number; createdAt: string; text: string }
  | {
      type: 'tool_call';
      id: string;
      seq: number;
      createdAt: string;
      toolUseId: string;
      name: string;
      input: Record<string, unknown>;
    }
  | {
      type: 'tool_result';
      id: string;
      seq: number;
      createdAt: string;
      toolUseId: string;
      content: string;
      isError: boolean;
      /** The structured half of a result — aggregate rows, mostly — for a
       *  chart to render from. `null` for every tool result that has nothing
       *  to plot, which is most of them. Never parsed out of `content`. */
      data: Record<string, unknown> | null;
    };

export interface ConversationDetail extends Conversation {
  events: ConversationEvent[];
  /** Non-null while a worker is still generating. Present on every page load,
   *  which is how a refreshed tab knows to reattach instead of assuming the
   *  transcript it just fetched is the end of the story. */
  activeTask: Task | null;
}

export interface SendMessageReceipt {
  taskId: string;
  /** The seq of the message just written — where the caller should resume from. */
  seq: number;
}

export const conversationKeys = {
  /**
   * Also the invalidation prefix. Every other key below starts with it, so
   * invalidating `all` refreshes the list, the archive and any open transcript
   * — which is what pinning, archiving and deleting all want.
   */
  all: ['conversations'] as const,
  archive: ['conversations', 'archive'] as const,
  detail: (id: string) => ['conversations', id] as const,
};

/**
 * The live list, or the archive. Never both: they are two views, and the
 * backend orders each one (pinned first, then newest) so the client does not
 * re-sort what it was handed.
 */
export const listConversations = (options?: { archived?: boolean }) =>
  apiFetch<Conversation[]>(options?.archived ? '/conversations?archived=true' : '/conversations');

export const createConversation = () =>
  apiFetch<Conversation>('/conversations', { method: 'POST' });

export const getConversation = (id: string) => apiFetch<ConversationDetail>(`/conversations/${id}`);

/** Queues a turn. Returns a receipt, not an answer — watch the stream for that. */
export const sendMessage = (id: string, content: string) =>
  apiFetch<SendMessageReceipt>(`/conversations/${id}/messages`, {
    body: JSON.stringify({ content }),
    method: 'POST',
  });

export const cancelTurn = (id: string) =>
  apiFetch<Task | null>(`/conversations/${id}/cancel`, { method: 'POST' });

/** Rename, pin, or archive. Send only the keys you mean to change. */
export const updateConversation = (id: string, patch: ConversationPatch) =>
  apiFetch<Conversation>(`/conversations/${id}`, {
    body: JSON.stringify(patch),
    method: 'PATCH',
  });

export const deleteConversation = (id: string) =>
  apiFetch<null>(`/conversations/${id}`, { method: 'DELETE' });

/**
 * Merge the fetched transcript with what arrived over the stream.
 *
 * Both sources carry the same events with the same `seq`, and they overlap on
 * purpose — the stream replays from a cursor rather than trying to hand off
 * precisely. Deduplicating here means neither side has to be exact, and a
 * refetch mid-stream cannot produce a duplicated or missing row.
 */
export function mergeEvents(
  persisted: ConversationEvent[],
  streamed: ConversationEvent[],
): ConversationEvent[] {
  const bySeq = new Map<number, ConversationEvent>();
  for (const event of persisted) bySeq.set(event.seq, event);
  for (const event of streamed) bySeq.set(event.seq, event);
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq);
}
