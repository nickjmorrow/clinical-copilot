import { describe, expect, it } from 'vitest';

import {
  type AgeBand,
  dimensionFromLogic,
  emptyDimension,
  emptyMeasure,
  emptyPredicate,
  measureFromLogic,
  type Predicate,
  predicateFromLogic,
} from 'src/predicates';

describe('predicateFromLogic', () => {
  it('round-trips an observation threshold', () => {
    const logic = {
      codes: ['33914-3'],
      most_recent: true,
      operator: '<',
      type: 'observation_threshold',
      units: ['mL/min'],
      value: 60,
    };
    expect(predicateFromLogic(logic)).toEqual(logic);
  });

  it('round-trips a medication attribute with a recency window', () => {
    const logic = {
      attribute: 'nephrotoxic_risk',
      exposure: 'recent',
      in: ['high', 'moderate'],
      type: 'medication_attribute',
      within_days: 730,
    };
    expect(predicateFromLogic(logic)).toEqual(logic);
  });

  it('defaults most_recent to true when absent, matching the backend validator', () => {
    const result = predicateFromLogic({
      codes: ['33914-3'],
      operator: '<',
      type: 'observation_threshold',
      units: ['mL/min'],
      value: 60,
    });
    expect(result).toMatchObject({ most_recent: true });
  });

  it('recurses into all_of members', () => {
    const logic = {
      of: [
        { operator: '>=', type: 'age_threshold', value: 65 },
        { status: 'alive', type: 'vital_status' },
      ],
      type: 'all_of',
    };
    const result = predicateFromLogic(logic) as { of: Predicate[]; type: string };
    expect(result.type).toBe('all_of');
    expect(result.of).toHaveLength(2);
    expect(result.of[0]).toEqual({ operator: '>=', type: 'age_threshold', value: 65 });
  });

  it('recurses into a negated member', () => {
    const logic = { of: { term: 'nephrotoxic medication', type: 'term' }, type: 'not' };
    expect(predicateFromLogic(logic)).toEqual(logic);
  });

  it('falls back to a fresh default for an unrecognised type, rather than throwing', () => {
    expect(() => predicateFromLogic({ type: 'drop_table' })).not.toThrow();
    expect(predicateFromLogic({ type: 'drop_table' }).type).toBe('age_threshold');
  });

  it('falls back for a malformed value rather than producing garbage', () => {
    const result = predicateFromLogic({
      codes: 'not an array',
      operator: 'like',
      type: 'observation_threshold',
      value: 'sixty',
    });
    expect(result).toMatchObject({ codes: [], operator: '<', value: 0 });
  });
});

describe('measureFromLogic', () => {
  it('round-trips an observation aggregate', () => {
    const logic = {
      aggregate: 'avg',
      codes: ['33914-3'],
      type: 'observation_aggregate',
      units: ['mL/min'],
    };
    expect(measureFromLogic(logic)).toEqual(logic);
  });

  it('defaults to patient_count for anything else', () => {
    expect(measureFromLogic({ type: 'unknown' })).toEqual({ type: 'patient_count' });
  });
});

describe('dimensionFromLogic', () => {
  it('round-trips an age band', () => {
    const logic = {
      bands: [
        { label: 'under 65', upto: 65 },
        { label: '65+', upto: null },
      ],
      type: 'age_band',
    };
    expect(dimensionFromLogic(logic)).toEqual(logic);
  });

  it('falls back to two default bands when fewer than two survive parsing', () => {
    const result = dimensionFromLogic({ bands: [{ label: 'only one' }], type: 'age_band' });
    expect((result as AgeBand).bands.length).toBeGreaterThanOrEqual(2);
  });

  it('round-trips a medication group', () => {
    const logic = {
      attribute: 'nephrotoxic_risk',
      exposure: 'active',
      type: 'medication_group',
      within_days: null,
    };
    expect(dimensionFromLogic(logic)).toEqual(logic);
  });

  it('defaults to a patient column for anything else', () => {
    expect(dimensionFromLogic({ type: 'unknown' })).toEqual({
      column: 'sex',
      type: 'patient_column',
    });
  });
});

describe('the empty-value constructors', () => {
  it('give every predicate type a value that round-trips through predicateFromLogic', () => {
    for (const type of [
      'observation_threshold',
      'medication_attribute',
      'age_threshold',
      'vital_status',
      'term',
      'all_of',
      'any_of',
      'not',
    ] as const) {
      const fresh = emptyPredicate(type);
      expect(predicateFromLogic(fresh)).toEqual(fresh);
    }
  });

  it('give every measure type a value that round-trips', () => {
    for (const type of ['patient_count', 'observation_aggregate'] as const) {
      const fresh = emptyMeasure(type);
      expect(measureFromLogic(fresh)).toEqual(fresh);
    }
  });

  it('give every dimension type a value that round-trips', () => {
    for (const type of ['patient_column', 'age_band', 'medication_group'] as const) {
      const fresh = emptyDimension(type);
      expect(dimensionFromLogic(fresh)).toEqual(fresh);
    }
  });
});
