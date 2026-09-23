import { describe, expect, it } from 'vitest';
import { cohortQuery, describeOutcome, readCohortCall, readCohortOutcome } from 'src/cohortCall';

const ROSTER_INPUT = {
  columns: [],
  group_by: [],
  measures: [],
  question: 'who is on a nephrotoxic drug with bad kidneys?',
  terms: ['impaired renal function', 'nephrotoxic medication'],
};

const AGGREGATE_INPUT = {
  columns: [],
  group_by: ['age band'],
  measures: ['average eGFR'],
  question: 'average eGFR by age band',
  terms: ['impaired renal function'],
};

describe('readCohortCall', () => {
  it('reads a patient-list call', () => {
    expect(readCohortCall('find_patients', ROSTER_INPUT)).toEqual({
      groupBy: [],
      measures: [],
      question: 'who is on a nephrotoxic drug with bad kidneys?',
      terms: ['impaired renal function', 'nephrotoxic medication'],
    });
  });

  it('reads an aggregate call', () => {
    expect(readCohortCall('find_patients', AGGREGATE_INPUT)).toMatchObject({
      groupBy: ['age band'],
      measures: ['average eGFR'],
    });
  });

  it('drops a group-by that has no measure, because the tool ignored it', () => {
    expect(
      readCohortCall('find_patients', { ...ROSTER_INPUT, group_by: ['age band'] })?.groupBy,
    ).toEqual([]);
  });

  it('is null for another tool, no filter, or a malformed argument', () => {
    expect(readCohortCall('current_time', ROSTER_INPUT)).toBeNull();
    expect(readCohortCall('find_patients', { ...ROSTER_INPUT, terms: [] })).toBeNull();
    expect(readCohortCall('find_patients', { ...ROSTER_INPUT, terms: ['ok', 3] })).toBeNull();
  });
});

describe('readCohortOutcome', () => {
  it('reads the count an answer carries', () => {
    expect(readCohortOutcome({ aggregate: false, rowCount: 8, truncated: false })).toEqual({
      aggregate: false,
      rowCount: 8,
      truncated: false,
    });
  });

  it('is null when no query ran', () => {
    expect(readCohortOutcome(null)).toBeNull();
  });

  it('reads an aggregate recorded before the count was part of the data', () => {
    const legacy = { columns: ['age band'], groupBy: [], measures: [], rows: [{}, {}, {}] };
    expect(readCohortOutcome(legacy)).toEqual({ aggregate: true, rowCount: 3, truncated: false });
  });
});

describe('cohortQuery', () => {
  it('asks for every returnable column for a patient list', () => {
    const call = readCohortCall('find_patients', ROSTER_INPUT);
    if (!call) throw new Error('expected a call');
    expect(cohortQuery(call, { aggregate: false, rowCount: 8, truncated: false })).toEqual({
      columns: ['patient_id', 'age', 'sex', 'race', 'state'],
      terms: ['impaired renal function', 'nephrotoxic medication'],
    });
  });

  it('asks an aggregate exactly as it was asked', () => {
    const call = readCohortCall('find_patients', AGGREGATE_INPUT);
    if (!call) throw new Error('expected a call');
    expect(cohortQuery(call, { aggregate: true, rowCount: 5, truncated: false })).toEqual({
      groupBy: ['age band'],
      measures: ['average eGFR'],
      terms: ['impaired renal function'],
    });
  });
});

describe('describeOutcome', () => {
  it('counts patients and groups, singular and plural', () => {
    expect(describeOutcome({ aggregate: false, rowCount: 8, truncated: false })).toBe(
      '8 matching patients',
    );
    expect(describeOutcome({ aggregate: false, rowCount: 1, truncated: false })).toBe(
      '1 matching patient',
    );
    expect(describeOutcome({ aggregate: true, rowCount: 5, truncated: false })).toBe('5 groups');
  });

  it('says when the rows are a capped page rather than the whole answer', () => {
    expect(describeOutcome({ aggregate: false, rowCount: 100, truncated: true })).toBe(
      '100 matching patients shown — more match than this page holds',
    );
  });
});
