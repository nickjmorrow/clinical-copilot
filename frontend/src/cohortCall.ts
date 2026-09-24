import type { CohortQuery } from 'src/api/cohort';

/**
 * A `find_patients` call, read back out of the transcript: what was asked,
 * what it found, and how to ask it again.
 *
 * The model's arguments *are* a structured question — defined terms,
 * measures, dimensions — which is what lets a chat answer offer the same
 * things a saved question does: save it, export it, list the patients behind
 * it. Nothing here re-derives an answer; it only reads what the tool call
 * already recorded.
 */

export interface CohortCall {
  groupBy: string[];
  measures: string[];
  /** The user's question in their own words, as the model passed it. */
  question: string;
  terms: string[];
}

export interface CohortOutcome {
  aggregate: boolean;
  rowCount: number;
  /** The rows are a capped page; more matched. */
  truncated: boolean;
}

// Mirrors `SELECTABLE` in backend/app/clinical/columns.py — every column a
// patient list may return. The model usually asks for the default three;
// "show patients" asks for all five.
const RETURNABLE_COLUMNS = ['patient_id', 'age', 'sex', 'race', 'state'];

function stringArray(value: unknown): null | string[] {
  if (!Array.isArray(value)) return null;
  const strings: string[] = [];
  for (const item of value as unknown[]) {
    if (typeof item !== 'string') return null;
    strings.push(item);
  }
  return strings;
}

/** The call's arguments as a question, or null for any other tool — or for a
 *  call with no filter, which could never have been answered. */
export function readCohortCall(name: string, input: Record<string, unknown>): CohortCall | null {
  if (name !== 'find_patients') return null;
  const terms = stringArray(input.terms);
  if (terms === null || terms.length === 0) return null;
  const measures = stringArray(input.measures) ?? [];
  return {
    // A group-by without a measure is ignored by the tool, so it is not
    // part of the question that was actually answered.
    groupBy: measures.length > 0 ? (stringArray(input.group_by) ?? []) : [],
    measures,
    question: typeof input.question === 'string' ? input.question : '',
    terms,
  };
}

/**
 * What an answered call found, or null when no query ran — a clarification or
 * a refusal carries no data.
 *
 * Tolerant of every shape ever written, because the transcript is
 * append-only (AGENTS.md > The transcript): an answer recorded before the
 * count was part of the data is still on screen. An aggregate from then
 * carried its rows and nothing else, so its count is the number of rows; a
 * patient list from then carried nothing, and is indistinguishable from a
 * clarification — so it gets no result block, which is the honest reading.
 */
export function readCohortOutcome(data: null | Record<string, unknown>): CohortOutcome | null {
  if (data === null) return null;
  if (typeof data.rowCount === 'number') {
    return {
      aggregate: data.aggregate === true,
      rowCount: data.rowCount,
      truncated: data.truncated === true,
    };
  }
  if (Array.isArray(data.rows)) {
    return { aggregate: true, rowCount: data.rows.length, truncated: false };
  }
  return null;
}

/**
 * The same question as a one-off query, for the CSV export and "show
 * patients": an aggregate exactly as asked, a patient list with every
 * returnable column rather than the three the model usually picks.
 */
export function cohortQuery(call: CohortCall, outcome: CohortOutcome): CohortQuery {
  if (outcome.aggregate) {
    return { groupBy: call.groupBy, measures: call.measures, terms: call.terms };
  }
  return { columns: RETURNABLE_COLUMNS, terms: call.terms };
}

function count(n: number, noun: string): string {
  return `${n.toLocaleString()} ${noun}${n === 1 ? '' : 's'}`;
}

/** The line a result leads with: "8 matching patients", "5 groups". A capped
 *  page says so, because "100 patients" reads as a total when it is not. */
export function describeOutcome(outcome: CohortOutcome): string {
  const text = count(outcome.rowCount, outcome.aggregate ? 'group' : 'matching patient');
  return outcome.truncated ? `${text} shown — more match than this page holds` : text;
}
