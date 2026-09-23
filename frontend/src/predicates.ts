/**
 * The shapes a `clinical_definitions.logic` value may take, mirroring
 * `app/clinical/predicates.py` exactly — including its field names.
 *
 * **Deliberately snake_case, unlike everything else this app fetches.**
 * `logic` is stored and read as raw JSONB; nothing converts it to or from
 * camelCase the way `wire.ApiSchema` does for the rest of the API surface
 * (see `src/api/client.ts`). Giving these types camelCase fields would mean a
 * translation layer whose only job is to reintroduce the mismatch it just
 * removed — these types describe the wire format on purpose.
 *
 * `parse_predicate`/`parse_measure`/`parse_dimension` on the backend are the
 * actual validator; nothing here is trusted until the backend has parsed it
 * too, which is what the editor's Preview button and the save path both do.
 */

export const COMPARISONS = ['<', '<=', '>', '>=', '='] as const;
export type Comparison = (typeof COMPARISONS)[number];

export const EXPOSURES = ['active', 'recent', 'ever'] as const;
export type Exposure = (typeof EXPOSURES)[number];

export const VITAL_STATUSES = ['alive', 'deceased'] as const;
export type VitalStatusValue = (typeof VITAL_STATUSES)[number];

export const AGGREGATES = ['avg', 'min', 'max', 'median'] as const;
export type AggregateFn = (typeof AGGREGATES)[number];

export const PATIENT_COLUMNS = ['sex', 'race', 'state'] as const;
export type PatientColumnName = (typeof PATIENT_COLUMNS)[number];

// ------------------------------------------------------------------ filters

export interface ObservationThreshold {
  type: 'observation_threshold';
  codes: string[];
  units: string[];
  operator: Comparison;
  value: number;
  most_recent: boolean;
}

export interface MedicationAttribute {
  type: 'medication_attribute';
  attribute: string;
  in: string[];
  exposure: Exposure;
  within_days: number | null;
}

export interface AgeThreshold {
  type: 'age_threshold';
  operator: Comparison;
  value: number;
}

export interface VitalStatus {
  type: 'vital_status';
  status: VitalStatusValue;
}

export interface TermReference {
  type: 'term';
  term: string;
}

export interface AnyOf {
  type: 'any_of';
  of: Predicate[];
}

export interface AllOf {
  type: 'all_of';
  of: Predicate[];
}

export interface Not {
  type: 'not';
  of: Predicate;
}

export type Predicate =
  | AgeThreshold
  | AllOf
  | AnyOf
  | MedicationAttribute
  | Not
  | ObservationThreshold
  | TermReference
  | VitalStatus;

export const PREDICATE_TYPES: Predicate['type'][] = [
  'observation_threshold',
  'medication_attribute',
  'age_threshold',
  'vital_status',
  'term',
  'all_of',
  'any_of',
  'not',
];

// ----------------------------------------------------------------- measures

export interface PatientCount {
  type: 'patient_count';
}

export interface ObservationAggregate {
  type: 'observation_aggregate';
  codes: string[];
  units: string[];
  aggregate: AggregateFn;
}

export type Measure = ObservationAggregate | PatientCount;

export const MEASURE_TYPES: Measure['type'][] = ['patient_count', 'observation_aggregate'];

// --------------------------------------------------------------- dimensions

export interface PatientColumn {
  type: 'patient_column';
  column: PatientColumnName;
}

export interface AgeBand {
  type: 'age_band';
  bands: { label: string; upto: number | null }[];
}

export interface MedicationGroup {
  type: 'medication_group';
  attribute: string;
  exposure: Exposure;
  within_days: number | null;
}

export type Dimension = AgeBand | MedicationGroup | PatientColumn;

export const DIMENSION_TYPES: Dimension['type'][] = [
  'patient_column',
  'age_band',
  'medication_group',
];

// -------------------------------------------------------- fresh, per type

export function emptyPredicate(type: Predicate['type']): Predicate {
  switch (type) {
    case 'observation_threshold': {
      return {
        codes: [],
        most_recent: true,
        operator: '<',
        type,
        units: [],
        value: 0,
      };
    }
    case 'medication_attribute': {
      return { attribute: 'nephrotoxic_risk', exposure: 'active', in: [], type, within_days: null };
    }
    case 'age_threshold': {
      return { operator: '>=', type, value: 65 };
    }
    case 'vital_status': {
      return { status: 'alive', type };
    }
    case 'term': {
      return { term: '', type };
    }
    case 'all_of':
    case 'any_of': {
      return { of: [emptyPredicate('age_threshold'), emptyPredicate('age_threshold')], type };
    }
    case 'not': {
      return { of: emptyPredicate('term'), type };
    }
  }
}

export function emptyMeasure(type: Measure['type']): Measure {
  if (type === 'patient_count') return { type };
  return { aggregate: 'avg', codes: [], type, units: [] };
}

export function emptyDimension(type: Dimension['type']): Dimension {
  switch (type) {
    case 'patient_column': {
      return { column: 'sex', type };
    }
    case 'age_band': {
      return {
        bands: [
          { label: 'under 65', upto: 65 },
          { label: '65+', upto: null },
        ],
        type,
      };
    }
    case 'medication_group': {
      return { attribute: 'nephrotoxic_risk', exposure: 'active', type, within_days: null };
    }
  }
}

// ------------------------------------------------------------- from raw JSON
//
// Every one of these takes `unknown` rather than a typed shape, on purpose:
// a saved definition's `logic` is only as trustworthy as whatever last wrote
// it — for now always this same editor or the seed, but there is no reason
// to trust that at compile time — and the point of accepting `unknown` is
// that a `Predicate`/`Measure`/`Dimension` value already in hand (the tests
// below round-trip through exactly that) passes through the same runtime
// checks as anything else rather than needing its own escape hatch. Malformed
// input (a hand-edited row) falls back to a fresh default rather than
// throwing, so opening the editor never crashes on a row it did not create.

function asObject(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {};
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : [];
}

function asNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' ? value : fallback;
}

export function predicateFromLogic(raw: unknown): Predicate {
  const logic = asObject(raw);
  const type = logic.type;
  if (typeof type !== 'string' || !PREDICATE_TYPES.includes(type as Predicate['type'])) {
    return emptyPredicate('age_threshold');
  }
  const kind = type as Predicate['type'];

  switch (kind) {
    case 'observation_threshold': {
      return {
        codes: asStringArray(logic.codes),
        most_recent: logic.most_recent !== false,
        operator: COMPARISONS.includes(logic.operator as Comparison)
          ? (logic.operator as Comparison)
          : '<',
        type: kind,
        units: asStringArray(logic.units),
        value: asNumber(logic.value, 0),
      };
    }
    case 'medication_attribute': {
      return {
        attribute: typeof logic.attribute === 'string' ? logic.attribute : '',
        exposure: EXPOSURES.includes(logic.exposure as Exposure)
          ? (logic.exposure as Exposure)
          : 'active',
        in: asStringArray(logic.in),
        type: kind,
        within_days: typeof logic.within_days === 'number' ? logic.within_days : null,
      };
    }
    case 'age_threshold': {
      return {
        operator: COMPARISONS.includes(logic.operator as Comparison)
          ? (logic.operator as Comparison)
          : '>=',
        type: kind,
        value: asNumber(logic.value, 65),
      };
    }
    case 'vital_status': {
      return {
        status: VITAL_STATUSES.includes(logic.status as VitalStatusValue)
          ? (logic.status as VitalStatusValue)
          : 'alive',
        type: kind,
      };
    }
    case 'term': {
      return { term: typeof logic.term === 'string' ? logic.term : '', type: kind };
    }
    case 'all_of':
    case 'any_of': {
      const of = Array.isArray(logic.of) ? logic.of : [];
      const members = of.map((member) => predicateFromLogic(member));
      const fallback = emptyPredicate(kind) as AllOf | AnyOf;
      return { of: members.length >= 2 ? members : fallback.of, type: kind };
    }
    case 'not': {
      return {
        of: logic.of === undefined ? emptyPredicate('term') : predicateFromLogic(logic.of),
        type: kind,
      };
    }
  }
}

export function measureFromLogic(raw: unknown): Measure {
  const logic = asObject(raw);
  if (logic.type === 'observation_aggregate') {
    return {
      aggregate: AGGREGATES.includes(logic.aggregate as AggregateFn)
        ? (logic.aggregate as AggregateFn)
        : 'avg',
      codes: asStringArray(logic.codes),
      type: 'observation_aggregate',
      units: asStringArray(logic.units),
    };
  }
  return { type: 'patient_count' };
}

export function dimensionFromLogic(raw: unknown): Dimension {
  const logic = asObject(raw);
  switch (logic.type) {
    case 'age_band': {
      const bands = Array.isArray(logic.bands) ? logic.bands : [];
      const parsed = bands
        .filter(
          (band): band is Record<string, unknown> => typeof band === 'object' && band !== null,
        )
        .map((band) => ({
          label: typeof band.label === 'string' ? band.label : '',
          upto: typeof band.upto === 'number' ? band.upto : null,
        }));
      return {
        bands: parsed.length >= 2 ? parsed : (emptyDimension('age_band') as AgeBand).bands,
        type: 'age_band',
      };
    }
    case 'medication_group': {
      return {
        attribute: typeof logic.attribute === 'string' ? logic.attribute : 'nephrotoxic_risk',
        exposure: EXPOSURES.includes(logic.exposure as Exposure)
          ? (logic.exposure as Exposure)
          : 'active',
        type: 'medication_group',
        within_days: typeof logic.within_days === 'number' ? logic.within_days : null,
      };
    }
    default: {
      return {
        column: PATIENT_COLUMNS.includes(logic.column as PatientColumnName)
          ? (logic.column as PatientColumnName)
          : 'sex',
        type: 'patient_column',
      };
    }
  }
}
