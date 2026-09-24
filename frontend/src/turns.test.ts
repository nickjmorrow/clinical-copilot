import { describe, expect, it } from 'vitest';

import type { ConversationEvent } from 'src/api/conversations';
import { mergeEvents } from 'src/api/conversations';
import { toTurnItems } from 'src/turns';

/**
 * The fold from the event log to what gets drawn.
 *
 * This is the frontend's counterpart to `to_event_out()` on the backend, and it
 * is the one place where "a tool call and its result are two rows but one card"
 * is decided. Worth pinning precisely because the interesting cases — an
 * interrupted call, an out-of-order result — are the ones nobody reproduces by
 * hand.
 */

let seq = 0;
const at = (minute: number) => `2026-01-01T00:${String(minute).padStart(2, '0')}:00Z`;

const user = (text: string): ConversationEvent => ({
  createdAt: at(0),
  id: `u${String(++seq)}`,
  seq: seq,
  text,
  type: 'user_message',
});

const assistant = (text: string): ConversationEvent => ({
  createdAt: at(0),
  id: `a${String(++seq)}`,
  seq: seq,
  text,
  type: 'assistant_message',
});

const call = (toolUseId: string, minute = 0): ConversationEvent => ({
  createdAt: at(minute),
  id: `c${String(++seq)}`,
  input: { timezone: 'Asia/Tokyo' },
  name: 'current_time',
  seq: seq,
  toolUseId,
  type: 'tool_call',
});

const result = (
  toolUseId: string,
  minute = 0,
  isError = false,
  data: Record<string, unknown> | null = null,
): ConversationEvent => ({
  content: 'ok',
  createdAt: at(minute),
  data,
  id: `r${String(++seq)}`,
  isError,
  seq: seq,
  toolUseId,
  type: 'tool_result',
});

describe('toTurnItems', () => {
  it('pairs a tool call with the result that answered it', () => {
    const items = toTurnItems([user('hi'), call('t1', 0), result('t1', 1), assistant('done')]);

    expect(items.map((item) => item.kind)).toEqual(['user', 'tool', 'assistant']);
    const tool = items[1];
    expect(tool?.kind).toBe('tool');
    if (tool?.kind !== 'tool') throw new Error('unreachable');
    expect(tool.result).toBe('ok');
    expect(tool.durationMs).toBe(60_000);
    expect(tool.data).toBeNull();
  });

  it('carries the structured half of a result through for a chart to render from', () => {
    const aggregate = { columns: ['age band'], groupBy: ['age band'], measures: [], rows: [] };
    const items = toTurnItems([call('t1'), result('t1', 1, false, aggregate)]);

    const tool = items[0];
    if (tool?.kind !== 'tool') throw new Error('expected a tool item');
    expect(tool.data).toEqual(aggregate);
  });

  it('leaves an unanswered call running rather than inventing a result', () => {
    // A run that died between calling a tool and recording the answer. The
    // backend repairs this for the MODEL's history; the user's view shows it
    // for what it is, which is the honest thing to draw.
    const items = toTurnItems([call('t1')]);
    const tool = items[0];
    if (tool?.kind !== 'tool') throw new Error('expected a tool item');
    expect(tool.result).toBeNull();
    expect(tool.durationMs).toBeNull();
  });

  it('ignores a result whose call it has never seen', () => {
    // Happens on a resume with a cursor that lands between the two rows.
    // Dropping it is right: there is no card to attach it to.
    expect(toTurnItems([result('orphan')])).toEqual([]);
  });

  it('keys each item so React can identify it across a re-fold', () => {
    const items = toTurnItems([user('hi'), call('t1'), result('t1')]);
    const keys = items.map((item) => item.key);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it('marks an errored result without turning it into a missing one', () => {
    const items = toTurnItems([call('t1'), result('t1', 0, true)]);
    const tool = items[0];
    if (tool?.kind !== 'tool') throw new Error('expected a tool item');
    expect(tool.isError).toBe(true);
    expect(tool.result).toBe('ok');
  });
});

describe('mergeEvents', () => {
  it('deduplicates the deliberate overlap between fetch and stream by seq', () => {
    // AGENTS.md > Frontend: "Overlap and deduplicate; do not try to hand off
    // precisely." Both halves cover seq 2 here, which is the normal case and
    // not an error.
    const a = user('one');
    const b = assistant('two');
    const c = assistant('three');

    const merged = mergeEvents([a, b], [b, c]);
    expect(merged.map((event) => event.seq)).toEqual([a.seq, b.seq, c.seq]);
  });

  it('orders by seq regardless of which side arrived first', () => {
    const a = user('one');
    const b = assistant('two');
    expect(mergeEvents([b], [a]).map((event) => event.seq)).toEqual([a.seq, b.seq]);
  });

  it('lets the streamed copy win, since it is the newer read', () => {
    const persisted: ConversationEvent = { ...assistant('stale'), seq: 99 };
    const streamed: ConversationEvent = { ...assistant('fresh'), seq: 99 };
    const merged = mergeEvents([persisted], [streamed]);
    expect(merged).toHaveLength(1);
    expect(merged[0]).toBe(streamed);
  });
});
