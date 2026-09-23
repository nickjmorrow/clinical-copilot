import { apiFetch } from 'src/api/client';

/**
 * One question the system could not resolve, ranked by how often it has come
 * up — SEMANTIC_LAYER.md § 14. Mirrors `UnresolvedTermOut` in
 * backend/app/api/schemas.py.
 */
export interface UnresolvedTerm {
  rawQuestion: string;
  count: number;
  lastAsked: string;
  askedBy: string[];
}

export const auditKeys = {
  unresolvedTerms: ['audit', 'unresolvedTerms'] as const,
};

export const listUnresolvedTerms = () => apiFetch<UnresolvedTerm[]>('/audit/unresolved-terms');
