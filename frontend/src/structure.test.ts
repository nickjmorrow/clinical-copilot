import { existsSync, readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Structural tests: the frontend conventions, checked by a machine.
 *
 * `eslint.config.js` already enforces the mechanical half of the contract, and
 * anything it can express belongs there rather than here — a rule in two places
 * is a rule that will disagree with itself. What is left is the handful of
 * rules that are about the *shape of the tree*: which directory may import
 * what, and whether a file is named after what it exports.
 *
 * The backend's counterpart, with a longer note on what a structural test is
 * for and what does not belong in one, is
 * `backend/tests/structure/test_conventions.py`.
 */

const SRC = new URL('.', import.meta.url).pathname;

function walk(directory: string): string[] {
  const out: string[] = [];
  const entries = readdirSync(directory, { withFileTypes: true });
  for (const entry of entries) {
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else if (/\.tsx?$/.test(entry.name)) out.push(full);
  }
  return out;
}

const FILES = walk(SRC).filter((file) => !file.endsWith('.test.ts'));

const read = (file: string) => readFileSync(file, 'utf8');
const relative = (file: string) => file.slice(SRC.length);

// --------------------------------------------------------- semantic colours
//
// Every colour is a semantic token, never a literal: `bg-surface`, not
// `bg-slate-50`; `text-danger`, not `text-red-700` (CONVENTIONS.md > Structural
// tests, "No literal Tailwind colour anywhere in `src/`"). That is
// what makes a theme a block of variable values rather than a `dark:` class on
// every element. The trap is opacity: `border-black/10` is a hairline on one
// background and invisible on the other, which is why a fraction is written
// against `ink`.
//
// Prettier sorts class strings and eslint has no idea what is inside one, so
// nothing else in the toolchain can see this.

const TAILWIND_PALETTE = [
  'slate',
  'gray',
  'zinc',
  'neutral',
  'stone',
  'red',
  'orange',
  'amber',
  'yellow',
  'lime',
  'green',
  'emerald',
  'teal',
  'cyan',
  'sky',
  'blue',
  'indigo',
  'violet',
  'purple',
  'fuchsia',
  'pink',
  'rose',
  'black',
  'white',
];

const COLOUR_UTILITIES = [
  'bg',
  'text',
  'border',
  'ring',
  'outline',
  'divide',
  'fill',
  'stroke',
  'shadow',
  'accent',
  'caret',
  'decoration',
  'placeholder',
  'from',
  'via',
  'to',
];

const LITERAL_COLOUR = new RegExp(
  String.raw`\b(?:${COLOUR_UTILITIES.join('|')})-(?:${TAILWIND_PALETTE.join('|')})\b`,
  'g',
);

describe('colours are semantic tokens', () => {
  it('uses no literal Tailwind palette colour anywhere in src/', () => {
    const offenders = FILES.flatMap((file) => {
      const hits = [...read(file).matchAll(LITERAL_COLOUR)].map((match) => match[0]);
      return hits.map((hit) => `${relative(file)}: ${hit}`);
    });

    expect(
      offenders,
      'Use a token from the @theme block in src/index.css — `bg-surface`, `text-danger`, ' +
        '`text-on-accent`. For a fraction of a colour use `ink` (`border-ink/10`), which inverts ' +
        'with the theme where `black` and `white` do not. See CONVENTIONS.md > Frontend.',
    ).toEqual([]);
  });

  it('declares every token it needs in one place', () => {
    // A sanity check on the rule above: if the @theme block ever empties out,
    // the deny-list would pass while nothing worked.
    const css = readFileSync(path.join(SRC, 'index.css'), 'utf8');
    const tokens = [...css.matchAll(/--color-([\w-]+):/g)].map((match) => match[1]);
    expect(new Set(tokens)).toContain('ink');
    expect(new Set(tokens)).toContain('on-accent');
  });
});

// ------------------------------------------------------- the view model is pure
//
// CONVENTIONS.md > Layout > The `.ts` files at the top level are the view
// model: they are "pure functions with no React in them, which is why they are
// not in `components/`." The same holds for `src/api/`, the HTTP boundary.
//
// This is the rule that decays first. A hook is one import away, and the moment
// one lands the fold stops being testable without a renderer — which is exactly
// how the suite above would stop existing.

describe('the view model and the API boundary contain no React', () => {
  const pure = FILES.filter(
    (file) => relative(file).startsWith('api/') || /^[\w-]+\.ts$/.test(relative(file)),
  );

  it.each(pure.map((file) => relative(file)))('%s imports no React', (name) => {
    const source = read(path.join(SRC, name));
    expect(/from 'react(-dom)?'/.test(source)).toBe(false);
  });
});

// ---------------------------------------------------- one thing, named for it
//
// CONVENTIONS.md > Frontend: "One component per file, default export, named to match
// the file." `react/no-multi-comp` counts definitions and
// `unicorn/filename-case` checks the case, but neither checks that the name in
// the file is the name on the file — which is the half that makes a component
// greppable.

const DEFAULT_EXPORT = /export default (?:function |class |memo\(|forwardRef\()?(\w+)/;

describe('a file is named after what it exports', () => {
  const named = FILES.filter(
    (file) => relative(file).startsWith('components/') || relative(file).startsWith('hooks/'),
  );

  it.each(named.map((file) => relative(file)))('%s', (name) => {
    const expected = name.split('/', 2)[1]?.replace(/\.tsx?$/, '');
    const match = DEFAULT_EXPORT.exec(read(path.join(SRC, name)));

    expect(match, `${name} has no default export`).not.toBeNull();
    expect(match?.[1]).toBe(expected);
  });
});

// ------------------------------------------- the view model is tested in place
//
// CONVENTIONS.md > Layout > Where tests go: "Frontend tests sit beside what they
// test: `turns.test.ts` next to `turns.ts`. Vitest finds them anywhere, the
// file it covers is one line away in the listing, and a module with no
// neighbouring test is visible at a glance."
//
// The top-level `.ts` files are pure functions of their input — that is the
// whole reason they are not in `components/` — so there is no excuse for one
// without a test, and no renderer needed to write it. This is the check that
// keeps the bar where CONVENTIONS.md puts it for putting a file there at all.

describe('every top-level view-model module has a test beside it', () => {
  const modules = FILES.filter(
    (file) => /^[\w-]+\.ts$/.test(relative(file)) && relative(file) !== 'vite-env.d.ts',
  );

  it.each(modules.map((file) => relative(file)))('%s', (name) => {
    const spec = path.join(SRC, name.replace(/\.ts$/, '.test.ts'));
    expect(
      existsSync(spec),
      `${name} is a pure module at the top level of src/ with no ${name.replace(
        /\.ts$/,
        '.test.ts',
      )} beside it. It takes data and returns data, so the test needs no renderer — write it, ` +
        'or the file belongs in a hook or a component instead. See CONVENTIONS.md > Layout.',
    ).toBe(true);
  });
});
