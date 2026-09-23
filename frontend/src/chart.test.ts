import { describe, expect, it } from 'vitest';

import { toChartData } from 'src/chart';

describe('toChartData', () => {
  it('builds one series per measure, one point per row', () => {
    const chart = toChartData({
      columns: ['age band', 'average eGFR'],
      groupBy: ['age band'],
      measures: ['average eGFR'],
      rows: [
        { 'age band': '18-44', 'average eGFR': 11.8 },
        { 'age band': '45-64', 'average eGFR': 19.1 },
      ],
    });

    expect(chart?.series).toEqual([
      {
        measure: 'average eGFR',
        points: [
          { label: '18-44', value: 11.8 },
          { label: '45-64', value: 19.1 },
        ],
      },
    ]);
  });

  it('joins more than one group-by dimension into one category label', () => {
    const chart = toChartData({
      columns: ['sex', 'age band', 'patient count'],
      groupBy: ['sex', 'age band'],
      measures: ['patient count'],
      rows: [{ 'age band': '65-79', 'patient count': 12, sex: 'female' }],
    });

    expect(chart?.series[0]?.points[0]?.label).toBe('female · 65-79');
  });

  it('falls back to an ordinal label when there is no group-by at all', () => {
    // A single aggregate with no dimension — "how many patients" alone — is
    // one row and one bar, not zero.
    const chart = toChartData({
      columns: ['patient count'],
      groupBy: [],
      measures: ['patient count'],
      rows: [{ 'patient count': 76 }],
    });

    expect(chart?.series[0]?.points).toEqual([{ label: '#1', value: 76 }]);
  });

  it('coerces a numeric value carried as a string', () => {
    // The JSON round-trip through the audit-log write and back can hand a
    // number back as text — see the Decimal-serialization fix in
    // backend/app/tools/find_patients.py. The chart must not go blank
    // because of it.
    const chart = toChartData({
      columns: ['average eGFR'],
      groupBy: [],
      measures: ['average eGFR'],
      rows: [{ 'average eGFR': '11.8' }],
    });

    expect(chart?.series[0]?.points).toEqual([{ label: '#1', value: 11.8 }]);
  });

  it('returns null for a plain cohort listing — nothing to plot', () => {
    expect(toChartData(null)).toBeNull();
    expect(
      toChartData({ columns: ['patient_id', 'age', 'sex'], groupBy: [], measures: [], rows: [] }),
    ).toBeNull();
  });

  it('returns null rather than throwing on a malformed or unexpected shape', () => {
    expect(toChartData(undefined)).toBeNull();
    expect(toChartData('not an object')).toBeNull();
    expect(toChartData({ measures: ['x'], rows: 'not an array' })).toBeNull();
    expect(toChartData({ measures: [1, 2], rows: [{}] })).toBeNull();
  });
});
