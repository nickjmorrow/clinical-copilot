/**
 * Small display formatters. Pure, no React — the same reason `turns.ts` sits
 * out here rather than in `components/`.
 */

const SECOND_MS = 1000;
const MINUTE_MS = 60 * SECOND_MS;

/** How long a tool took, at the precision a human cares about. */
export function formatDuration(ms: number): string {
  if (ms < SECOND_MS) return `${String(Math.round(ms))}ms`;
  if (ms < MINUTE_MS) return `${(ms / SECOND_MS).toFixed(1)}s`;

  const minutes = Math.floor(ms / MINUTE_MS);
  const seconds = Math.round((ms % MINUTE_MS) / SECOND_MS);
  return `${String(minutes)}m ${String(seconds)}s`;
}

/** Clock time for a transcript row, in the reader's own locale and zone. */
export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

/** A real instant (when a question was last asked) — date and clock time
 *  together, in the reader's own locale and zone. Unlike `formatDate`, this
 *  is not a calendar day that should read the same everywhere; it is a
 *  timestamp, and the reader's own zone is the right one to show it in. */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    month: 'short',
    year: 'numeric',
  });
}

/**
 * A calendar date (dataset provenance, an as-of date) — no clock time.
 *
 * `timeZone: 'UTC'` is load-bearing, not a stylistic default. A date-only ISO
 * string (`"2026-09-21"`, no time component) parses as UTC midnight, and
 * formatting that in the reader's *local* zone shifts it a day earlier for
 * anyone west of UTC — the dataset's as-of date is a calendar day, not an
 * instant, and should read the same regardless of where it is viewed from.
 */
export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
    year: 'numeric',
  });
}

/**
 * Tool arguments on one line, for the collapsed header.
 *
 * Long values are cut rather than wrapped: the header is a glance, and the
 * expanded view below it has the whole thing.
 */
export function summarizeToolInput(input: Record<string, unknown>, limit = 80): string {
  const entries = Object.entries(input);
  if (entries.length === 0) return 'no arguments';

  const rendered = entries
    .map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
    .join(', ');

  return rendered.length > limit ? `${rendered.slice(0, limit)}…` : rendered;
}

/**
 * A structured question on one line, in the vocabulary's own words:
 * `impaired renal function + elderly → average eGFR by age band`.
 *
 * The one rendering of "what was asked" — under a saved question's name, on a
 * dashboard tile, and in the header of a chat answer's query — so the same
 * question reads the same way wherever it appears.
 */
export function describeQuestion(question: {
  groupBy: string[];
  measures: string[];
  terms: string[];
}): string {
  let text = question.terms.join(' + ');
  if (question.measures.length > 0) text += ` → ${question.measures.join(', ')}`;
  if (question.groupBy.length > 0) text += ` by ${question.groupBy.join(', ')}`;
  return text;
}

/**
 * A failed turn's error as a person should read it.
 *
 * The worker records a failure as `code: message`. The code is for machines —
 * it is what decides whether a turn is retried, and what you grep the logs
 * for — and the message after it is already written for a reader. Showing
 * both put `out_of_credit:` in front of an apology.
 */
export function describeTurnError(error: string): string {
  const match = /^[a-z_]+: (.+)$/su.exec(error);
  return match?.[1] ?? error;
}
