import { apiFetch } from 'src/api/client';

/**
 * One term this app understands, mirroring `DefinedTermOut` in
 * backend/app/api/schemas.py.
 *
 * `why` is the justification for the threshold and is the reason this is worth
 * showing at all. There is deliberately no predicate here: what the term
 * *resolves to* is the assembler's business, and putting a number in front of
 * a reader invites them to reason about the number instead of the term.
 *
 * `kind` is `filter` | `measure` | `dimension` — which of the three arrays on
 * the model's tool this term belongs in.
 */
export interface DefinedTerm {
  term: string;
  kind: string;
  means: string;
  alsoCalled: string[];
  why: string;
}

/**
 * Which dataset is loaded, and what "now" means for it — SEMANTIC_LAYER.md
 * § 1. Every age and every "currently prescribed" in every answer is
 * relative to `asOfDate`, not the wall clock.
 */
export interface DatasetProvenance {
  source: string;
  asOfDate: string;
  patientCount: number;
  notes: string | null;
  loadedAt: string;
}

export interface ObservationCatalogEntry {
  code: string;
  display: string;
  category: string | null;
  unit: string | null;
  units: string[];
  observationCount: number;
  patientCount: number;
  isNumeric: boolean;
}

export interface Dataset {
  dataset: DatasetProvenance | null;
  patients: number;
  medications: number;
  prescriptions: number;
  observations: number;
  observationCatalog: ObservationCatalogEntry[];
  annotationValues: Record<string, string[]>;
  returnableColumns: string[];
  restrictedColumns: string[];
  maxRows: number;
}

export interface ClinicalContext {
  terms: DefinedTerm[];
  dataset: Dataset;
}

export async function fetchClinicalContext(signal?: AbortSignal): Promise<ClinicalContext> {
  return apiFetch<ClinicalContext>('/clinical/context', { signal });
}
