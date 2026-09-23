import { apiFetch } from 'src/api/client';
import type { DatasetProvenance } from 'src/api/clinical';

/**
 * One saved question — terms, measures and group-by names, never rows or SQL.
 * Mirrors `SavedQuestionOut` in backend/app/api/schemas.py. Re-running one
 * goes through the real definitions layer every time (`runSavedQuestion`
 * below), so an edited threshold is picked up rather than a stale answer
 * replayed — see CONVENTIONS.md's "no answer caching" line.
 */
export interface SavedQuestion {
  id: string;
  name: string;
  terms: string[];
  measures: string[];
  groupBy: string[];
  createdAt: string;
}

export interface SavedQuestionDraft {
  name: string;
  terms: string[];
  measures: string[];
  groupBy: string[];
}

/** One resolved filter, measure, or dimension — mirrors `ResolvedTermOut`. */
export interface ResolvedTerm {
  term: string;
  description: string;
  notes: string;
}

export interface Unmeasured {
  term: string;
  count: number;
}

/**
 * The result of running a saved question right now. Mirrors
 * `SavedQuestionRunOut` — `rows` is `Record<string, unknown>[]` rather than a
 * fixed shape because its keys are term names, not a schema: a cohort listing
 * keys by `patientId`/`age`/`sex`, an aggregate keys by whichever dimension
 * and measure terms were asked for.
 */
export interface SavedQuestionRun {
  outcome: string;
  aggregate: boolean;
  columns: string[];
  rows: Record<string, unknown>[];
  rowCount: number;
  truncated: boolean;
  resolvedTerms: ResolvedTerm[];
  resolvedMeasures: ResolvedTerm[];
  resolvedDimensions: ResolvedTerm[];
  unmeasured: Unmeasured[];
  dataset: DatasetProvenance | null;
  reason: string | null;
  unresolved: string[];
}

export const savedQuestionKeys = {
  all: ['savedQuestions'] as const,
};

export const listSavedQuestions = () => apiFetch<SavedQuestion[]>('/saved-questions');

export const createSavedQuestion = (draft: SavedQuestionDraft) =>
  apiFetch<SavedQuestion>('/saved-questions', { body: JSON.stringify(draft), method: 'POST' });

export const deleteSavedQuestion = (id: string) =>
  apiFetch<null>(`/saved-questions/${id}`, { method: 'DELETE' });

export const runSavedQuestion = (id: string) =>
  apiFetch<SavedQuestionRun>(`/saved-questions/${id}/run`, { method: 'POST' });
