import { describe, expect, it } from 'vitest';
import { INPUT, LABEL, SIDEBAR_HEADING } from 'src/styles';

describe('INPUT', () => {
  it('uses the ink/surface tokens, never a literal Tailwind colour', () => {
    expect(INPUT).toContain('border-ink/10');
    expect(INPUT).toContain('bg-surface');
    expect(INPUT).toContain('text-ink');
  });

  it('shows focus state through the accent token', () => {
    expect(INPUT).toContain('focus:border-accent/50');
    expect(INPUT).toContain('focus:ring-accent/15');
  });
});

describe('LABEL', () => {
  it('is the small-caps field-label treatment, in the muted ink token', () => {
    expect(LABEL).toContain('text-ink-muted');
    expect(LABEL).toContain('uppercase');
  });
});

describe('SIDEBAR_HEADING', () => {
  it('is quieter than a field label, in the same muted ink token', () => {
    expect(SIDEBAR_HEADING).toContain('text-ink-muted');
    expect(SIDEBAR_HEADING).toContain('text-[10px]');
    expect(LABEL).toContain('text-[11px]');
  });
});
