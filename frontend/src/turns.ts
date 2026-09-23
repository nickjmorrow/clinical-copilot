import type { ConversationEvent } from 'src/api/conversations';

/**
 * One thing to draw.
 *
 * The transcript is stored as an append-only event log (see CONVENTIONS.md > The
 * transcript), which is the right shape for writing and the wrong shape for
 * rendering: a tool call and the result that answered it are two rows, and they
 * are one card on screen. `TurnItem` is the display shape, and `toTurnItems` is
 * the fold that gets there.
 *
 * There is only one such fold, and that is the point. `mergeEvents` has already
 * combined the fetched transcript with whatever arrived over the stream by the
 * time this runs, so a tool card mid-answer and the same card after a refresh
 * are built by the same code from the same rows. The single exception is the
 * live token preview, which is not an event at all and is replaced by the
 * durable `assistant_message` moments later.
 *
 * This lives outside `components/` because it is a pure function of the event
 * log with no React in it — the frontend's counterpart to `to_event_out()` in
 * `backend/app/api/schemas.py`.
 */
export type TurnItem =
  | { kind: 'assistant'; key: string; text: string }
  | {
      /** How long the tool took, or null while it is still running. */
      durationMs: null | number;
      isError: boolean;
      input: Record<string, unknown>;
      key: string;
      kind: 'tool';
      name: string;
      result: null | string;
      /** The structured half of the result, for a chart — see
       *  `ConversationEvent`'s `tool_result` variant. Null until the result
       *  arrives, same as `result` itself. */
      data: Record<string, unknown> | null;
    }
  | { kind: 'user'; key: string; text: string };

/** Fold the stored event log into renderable items, pairing each tool call
 *  with the result that answered it. A call with no result is a run that was
 *  interrupted — it stays on screen as "running…", which is the truth. */
export function toTurnItems(events: ConversationEvent[]): TurnItem[] {
  const items: TurnItem[] = [];
  const positions = new Map<string, number>();
  const startedAt = new Map<string, string>();

  for (const event of events) {
    switch (event.type) {
      case 'user_message': {
        items.push({ key: event.id, kind: 'user', text: event.text });
        break;
      }

      case 'assistant_message': {
        items.push({ key: event.id, kind: 'assistant', text: event.text });
        break;
      }

      case 'tool_call': {
        positions.set(event.toolUseId, items.length);
        startedAt.set(event.toolUseId, event.createdAt);
        items.push({
          data: null,
          durationMs: null,
          input: event.input,
          isError: false,
          key: event.toolUseId,
          kind: 'tool',
          name: event.name,
          result: null,
        });
        break;
      }

      case 'tool_result': {
        const index = positions.get(event.toolUseId);
        if (index === undefined) break;
        const target = items[index];
        if (target?.kind !== 'tool') break;

        // Server timestamps on both ends, so this is the tool's real duration
        // rather than anything the browser observed — and it survives a
        // refresh, which a client-side timer does not.
        const started = startedAt.get(event.toolUseId);
        const durationMs =
          started === undefined
            ? null
            : new Date(event.createdAt).getTime() - new Date(started).getTime();

        items[index] = {
          ...target,
          data: event.data,
          durationMs,
          isError: event.isError,
          result: event.content,
        };
        break;
      }
    }
  }

  return items;
}
