import { apiFetch } from 'src/api/client';

/**
 * One definition, with `logic` — the authoring view. Mirrors `DefinitionOut`
 * in backend/app/api/schemas.py. Distinct from `DefinedTerm` in
 * `src/api/clinical.ts`, which is what the chat panel shows and deliberately
 * withholds `logic` — see that file and SEMANTIC_LAYER.md § 2.
 */
/** A filter's claimed relationship to another filter — `subset_of` or
 * `disjoint_from` a named term — checked against the loaded dataset by
 * `check_model()` and surfaced as a `ModelWarning` on violation, the same way
 * a term matching nobody already is. Not editable in the form yet (same
 * status as `owner`/`reviewedAt`: on the wire, not yet a field a curator can
 * set here) — see SEMANTIC_LAYER.md § 13. */
export interface Invariant {
  type: 'disjoint_from' | 'subset_of';
  term: string;
}

export interface Definition {
  id: string;
  term: string;
  kind: 'dimension' | 'filter' | 'measure';
  entity: 'medication' | 'observation' | 'patient';
  description: string;
  logic: Record<string, unknown>;
  notes: string;
  synonyms: string[];
  invariants: Invariant[];
  status: 'deprecated' | 'draft' | 'published';
  owner: string | null;
  reviewedAt: string | null;
  version: number;
  updatedBy: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface DefinitionHistoryEntry {
  id: string;
  definitionId: string;
  term: string;
  version: number;
  action: 'created' | 'deleted' | 'updated';
  kind: string;
  entity: string;
  description: string;
  logic: Record<string, unknown>;
  notes: string;
  synonyms: string[];
  invariants: Invariant[];
  status: string;
  changedBy: string;
  changeReason: string;
  createdAt: string;
}

export interface ModelWarning {
  term: string;
  kind: string;
  message: string;
}

export interface DefinitionDraft {
  term: string;
  kind: 'dimension' | 'filter' | 'measure';
  entity: 'medication' | 'observation' | 'patient';
  description: string;
  logic: Record<string, unknown>;
  notes: string;
  synonyms: string[];
  invariants?: Invariant[];
  status: 'deprecated' | 'draft' | 'published';
  owner?: string | null;
  changeReason: string;
}

/** A patch: every field but `changeReason` is optional and absent means
 * unchanged, matching `definition_service.update_definition`. */
export type DefinitionPatch = Partial<Omit<DefinitionDraft, 'changeReason'>> & {
  changeReason: string;
};

export const definitionKeys = {
  all: ['definitions'] as const,
  detail: (id: string) => ['definitions', id] as const,
  history: (id: string) => ['definitions', id, 'history'] as const,
  modelCheck: ['definitions', 'modelCheck'] as const,
};

export const listDefinitions = () => apiFetch<Definition[]>('/clinical/definitions');

export const getDefinition = (id: string) => apiFetch<Definition>(`/clinical/definitions/${id}`);

export const getDefinitionHistory = (id: string) =>
  apiFetch<DefinitionHistoryEntry[]>(`/clinical/definitions/${id}/history`);

export const checkModel = () => apiFetch<ModelWarning[]>('/clinical/model/check');

/** `patientCount` is `null` for a measure or a dimension — neither has a
 * cohort of its own to preview. A rejected shape throws `ApiError` (422). */
export const previewDefinition = (kind: Definition['kind'], logic: Record<string, unknown>) =>
  apiFetch<{ patientCount: null | number }>('/clinical/definitions/preview', {
    body: JSON.stringify({ kind, logic }),
    method: 'POST',
  });

export const createDefinition = (draft: DefinitionDraft) =>
  apiFetch<Definition>('/clinical/definitions', { body: JSON.stringify(draft), method: 'POST' });

export const updateDefinition = (id: string, patch: DefinitionPatch) =>
  apiFetch<Definition>(`/clinical/definitions/${id}`, {
    body: JSON.stringify(patch),
    method: 'PATCH',
  });

export const publishDefinition = (id: string, changeReason: string) =>
  apiFetch<Definition>(`/clinical/definitions/${id}/publish`, {
    body: JSON.stringify({ changeReason }),
    method: 'POST',
  });

export const deleteDefinition = (id: string, changeReason: string) =>
  apiFetch<null>(`/clinical/definitions/${id}`, {
    body: JSON.stringify({ changeReason }),
    method: 'DELETE',
  });
