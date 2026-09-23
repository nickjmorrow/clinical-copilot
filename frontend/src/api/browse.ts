import { apiFetch } from 'src/api/client';
import type { DatasetProvenance } from 'src/api/clinical';

/**
 * One page of the raw patient table — SEMANTIC_LAYER.md § 3's governed table
 * browser. Mirrors `BrowsePageOut` in backend/app/api/schemas.py. `total` is
 * the whole scoped population, not this page's size.
 */
export interface BrowsePage {
  outcome: string;
  columns: string[];
  rows: Record<string, unknown>[];
  total: number;
  offset: number;
  limit: number;
  dataset: DatasetProvenance | null;
  reason: null | string;
}

export interface BrowseQuery {
  columns?: string[];
  offset?: number;
  limit?: number;
}

export const browsePatients = (query: BrowseQuery = {}) => {
  const params = new URLSearchParams();
  const columns = query.columns ?? [];
  for (const column of columns) params.append('columns', column);
  if (query.offset !== undefined) params.set('offset', String(query.offset));
  if (query.limit !== undefined) params.set('limit', String(query.limit));

  const search = params.toString();
  return apiFetch<BrowsePage>(`/clinical/patients${search ? `?${search}` : ''}`);
};
