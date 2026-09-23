import { describe, expect, it } from 'vitest';

import { describeQuestion, formatDuration, summarizeToolInput } from 'src/format';

// `formatTime` is deliberately untested: it formats in the reader's locale and
// zone, so any assertion here is an assertion about the machine running it.

describe('formatDuration', () => {
  it('uses whole milliseconds below a second', () => {
    expect(formatDuration(0)).toBe('0ms');
    expect(formatDuration(999)).toBe('999ms');
  });

  it('switches to seconds at one second', () => {
    expect(formatDuration(1000)).toBe('1.0s');
    expect(formatDuration(59_940)).toBe('59.9s');
  });

  it('switches to minutes at one minute', () => {
    expect(formatDuration(60_000)).toBe('1m 0s');
    expect(formatDuration(90_000)).toBe('1m 30s');
  });
});

describe('summarizeToolInput', () => {
  it('says so when there are no arguments at all', () => {
    expect(summarizeToolInput({})).toBe('no arguments');
  });

  it('renders strings bare and everything else as JSON', () => {
    expect(summarizeToolInput({ count: 3, name: 'Tokyo' })).toBe('count: 3, name: Tokyo');
  });

  it('truncates rather than wrapping, because the header is a glance', () => {
    const summary = summarizeToolInput({ body: 'x'.repeat(200) }, 20);
    expect(summary).toHaveLength(21);
    expect(summary.endsWith('…')).toBe(true);
  });
});

describe('describeQuestion', () => {
  it('joins filters with +', () => {
    expect(
      describeQuestion({ groupBy: [], measures: [], terms: ['elderly', 'nephrotoxic medication'] }),
    ).toBe('elderly + nephrotoxic medication');
  });

  it('adds measures after an arrow and dimensions after "by"', () => {
    expect(
      describeQuestion({
        groupBy: ['age band'],
        measures: ['average eGFR'],
        terms: ['impaired renal function'],
      }),
    ).toBe('impaired renal function → average eGFR by age band');
  });

  it('leaves out a group-by with no measure to group', () => {
    expect(describeQuestion({ groupBy: [], measures: ['patient count'], terms: ['elderly'] })).toBe(
      'elderly → patient count',
    );
  });
});
