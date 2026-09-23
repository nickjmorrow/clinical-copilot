import { describe, expect, it } from 'vitest';

import { splitStreamingMarkdown } from 'src/markdown';

/**
 * `splitStreamingMarkdown` decides what the markdown parser is allowed to see
 * while text is still arriving. Two properties matter more than any individual
 * case, and both are swept over every prefix of a message below:
 *
 *   1. **`stable + tail` reconstructs the input**, modulo the trailing blank
 *      lines the split drops as separator. Lose a character here and the answer
 *      on screen is quietly missing one.
 *   2. **`stable` only ever grows.** If it can shrink, the rendered half
 *      flickers and the memo it exists to enable is pointless.
 *
 * Call it the prefix-sweep test: every prefix of a real answer, rendered in
 * turn, exactly as a stream would deliver it.
 */

function sweep(full: string) {
  const lengths: number[] = [];
  const stables: string[] = [];
  for (let index = 0; index <= full.length; index++) {
    const prefix = full.slice(0, index);
    const { stable, tail } = splitStreamingMarkdown(prefix);

    // Property 1: nothing is lost. `stable` has trailing newlines stripped, so
    // rejoin with the separator the split removed and compare after trimming.
    const rejoined = stable === '' ? tail : `${stable}\n${tail}`;
    expect(rejoined.replaceAll(/\s+/g, ' ').trim()).toBe(prefix.replaceAll(/\s+/g, ' ').trim());

    lengths.push(stable.length);
    stables.push(stable);
  }
  return { lengths, stables };
}

const DOCUMENT = [
  'Here is a plan.',
  '',
  '- first item',
  '- second item',
  '',
  'And some code:',
  '',
  '```python',
  'def f():',
  '',
  '    return 1',
  '```',
  '',
  'Done.',
].join('\n');

describe('splitStreamingMarkdown', () => {
  it('never shrinks stable across any prefix of a message', () => {
    const { lengths, stables } = sweep(DOCUMENT);

    for (const [index, length] of lengths.entries()) {
      if (index === 0) continue;
      const previous = lengths[index - 1] ?? 0;
      expect(
        length,
        `stable shrank at prefix ${String(index)}:\n${JSON.stringify(stables[index - 1])}\n->\n${JSON.stringify(stables[index])}`,
      ).toBeGreaterThanOrEqual(previous);
    }
  });

  it('holds everything back until a block is actually complete', () => {
    expect(splitStreamingMarkdown('A partial sen')).toEqual({
      stable: '',
      tail: 'A partial sen',
    });
  });

  it('treats a closing fence as a boundary, since a code block gets no other', () => {
    // The last block of a message is never followed by a blank line. Without
    // the closing-fence case a finished code block would sit in `tail` as
    // literal backticks forever.
    const { stable, tail } = splitStreamingMarkdown('```js\nconst a = 1;\n```');
    expect(stable).toBe('```js\nconst a = 1;\n```');
    expect(tail).toBe('');
  });

  it('keeps an unclosed fence out of stable, blank lines and all', () => {
    const { stable, tail } = splitStreamingMarkdown(
      'Intro.\n\n```js\nconst a = 1;\n\nconst b = 2;',
    );
    expect(stable).toBe('Intro.');
    expect(tail).toBe('```js\nconst a = 1;\n\nconst b = 2;');
  });

  it('does not promote a block on a lone trailing newline', () => {
    // "- one\n" looks like a blank line followed by nothing, but the list may
    // be about to continue. Promoting it means giving it back a frame later.
    const { stable, tail } = splitStreamingMarkdown('- one\n');
    expect(stable).toBe('');
    expect(tail).toBe('- one\n');
  });

  it('promotes a block once a real blank line is followed by more text', () => {
    const { stable, tail } = splitStreamingMarkdown('- one\n\nN');
    expect(stable).toBe('- one');
    expect(tail).toBe('N');
  });

  it('returns an empty split for empty input', () => {
    expect(splitStreamingMarkdown('')).toEqual({ stable: '', tail: '' });
  });
});
