import { apiFetch, apiRequest } from 'src/api/client';
import type { SavedQuestionRun } from 'src/api/savedQuestions';

/**
 * An ad-hoc cohort or aggregate query — SEMANTIC_LAYER.md § 3's cohort
 * drilldown. Mirrors `CohortQueryIn` in backend/app/api/schemas.py. Unlike a
 * saved question, this asks once and persists nothing; `columns` is the one
 * field a saved question does not have, because "every returnable column"
 * is the whole reason to reach for this rather than `runSavedQuestion`.
 */
export interface CohortQuery {
  terms: string[];
  measures?: string[];
  groupBy?: string[];
  columns?: string[];
}

export const runCohortQuery = (query: CohortQuery) =>
  apiFetch<SavedQuestionRun>('/clinical/query', { body: JSON.stringify(query), method: 'POST' });

/**
 * The same query as `runCohortQuery`, as a CSV file the browser downloads.
 * `/clinical/export` returns the file directly rather than a `{ data, meta }`
 * envelope, so this goes through `apiRequest` and handles the response body
 * itself instead of `apiFetch`'s JSON unwrap.
 */
export async function downloadCohortCsv(query: CohortQuery): Promise<void> {
  const response = await apiRequest('/clinical/export', {
    body: JSON.stringify(query),
    method: 'POST',
  });
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement('a');
    link.href = url;
    link.download = 'cohort.csv';
    link.click();
  } finally {
    URL.revokeObjectURL(url);
  }
}
