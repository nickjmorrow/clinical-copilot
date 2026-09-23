import js from '@eslint/js';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import perfectionist from 'eslint-plugin-perfectionist';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import unicorn from 'eslint-plugin-unicorn';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import prettier from 'eslint-config-prettier';

/**
 * The frontend's half of the contract in CONVENTIONS.md.
 *
 * The backend has had `ruff` since the beginning; this is its counterpart, and
 * it is built the same way: take the broad recommended set, then turn off
 * individual rules with a note saying why. An `off` with a reason is a decision
 * someone can argue with later. A short `select` list is a decision nobody
 * recorded.
 *
 * About half of the contract is mechanical and lives here. The other half
 * ("server state is TanStack Query", "never render streamed text straight from
 * the stream") is judgement a linter cannot express, and is written down in
 * CONVENTIONS.md > Frontend. Neither replaces the other.
 */
export default tseslint.config(
  { ignores: ['dist', 'node_modules'] },

  js.configs.recommended,

  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      tseslint.configs.strictTypeChecked,
      tseslint.configs.stylisticTypeChecked,
      unicorn.configs.recommended,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    plugins: { perfectionist },
    rules: {
      // ---- CONVENTIONS.md rules, enforced ------------------------------------

      // "Absolute imports only (`src/api/client`). Relative paths stop being
      // readable three directories in." The backend's `ban-relative-imports`
      // is the same rule on the other side of the wire.
      'no-restricted-imports': [
        'error',
        {
          // "Answers are markdown; never enable raw HTML." `react-markdown`
          // builds elements; `rehype-raw` makes it set innerHTML instead, which
          // turns every model answer into an injection surface. The rule is
          // here rather than in a review checklist because it is one `pnpm add`
          // and one line away at any time.
          paths: [
            {
              message:
                'rehype-raw turns model output into raw HTML. Markdown.tsx must stay element-building (CONVENTIONS.md > Frontend).',
              name: 'rehype-raw',
            },
          ],
          patterns: [
            {
              group: ['./*', '../*'],
              message: 'Absolute imports only: use `src/...` (CONVENTIONS.md > Frontend).',
            },
          ],
        },
      ],

      // "SSE uses `fetch` + `ReadableStream`, never `EventSource`" —
      // EventSource cannot POST and cannot set headers, so it cannot carry the
      // token that `src/api/auth.ts` exists to supply.
      'no-restricted-globals': [
        'error',
        {
          message:
            'EventSource cannot set headers or POST. Use fetch + ReadableStream (src/api/stream.ts).',
          name: 'EventSource',
        },
      ],

      // The `void queryClient.invalidateQueries(...)` spelling already in the
      // code is this rule being followed by hand. Now it is checked.
      '@typescript-eslint/no-floating-promises': 'error',

      // Types are imported as types, so a type-only import can never pull a
      // module into the bundle at runtime.
      '@typescript-eslint/consistent-type-imports': [
        'error',
        { fixStyle: 'inline-type-imports', prefer: 'type-imports' },
      ],

      // A server logs; a browser app in production should not be narrating to
      // the console. `console.error` stays for the ErrorBoundary, which is the
      // only record that exists when a render throws.
      'no-console': ['error', { allow: ['error'] }],

      // ---- Ordering ------------------------------------------------------
      //
      // Already universal in `src/` — every object literal passed before this
      // was switched on. Worth enforcing precisely because it is arbitrary:
      // nobody should spend a review comment on it.
      'perfectionist/sort-imports': [
        'error',
        {
          groups: [['builtin', 'external'], 'internal', ['parent', 'sibling', 'index'], 'style'],
          internalPattern: ['^src/.*'],
          newlinesBetween: 'ignore',
          type: 'alphabetical',
        },
      ],
      'perfectionist/sort-jsx-props': ['error', { type: 'alphabetical' }],
      'perfectionist/sort-named-imports': ['error', { type: 'alphabetical' }],
      'perfectionist/sort-objects': ['error', { type: 'alphabetical' }],

      // NOT enabled: sort-interfaces / sort-object-types. The wire shapes in
      // `src/api/conversations.ts` mirror the field order of the Pydantic
      // models in `backend/app/api/schemas.py`, and keeping the two greppable
      // side by side is worth more than alphabetising them.

      // ---- Accommodations, with reasons ----------------------------------

      // Effect cleanups are `() => clearTimeout(t)` and `() => controller.abort()`.
      // That shorthand is the React idiom; the rule's real target is a
      // non-void function that returns a void call by accident.
      '@typescript-eslint/no-confusing-void-expression': ['error', { ignoreArrowShorthand: true }],

      // `?since=${seq}` is a number in a URL, which is the normal case.
      '@typescript-eslint/restrict-template-expressions': ['error', { allowNumber: true }],

      // `while (true)` around `reader.read()` is how you drain a ReadableStream.
      '@typescript-eslint/no-unnecessary-condition': [
        'error',
        { allowConstantLoopConditions: true },
      ],

      // ---- unicorn: off, and why -----------------------------------------

      // `null` is the wire format. The backend sends `null` for an absent task,
      // an unanswered tool call, a conversation with no title; `undefined` does
      // not survive JSON. Swapping them would make the TypeScript types stop
      // describing what actually arrives.
      'unicorn/no-null': 'off',

      // Would rename `props` to `properties` and `ref` to `reference`. Those
      // are React's own vocabulary, not abbreviations we chose.
      'unicorn/name-replacements': 'off',

      // Fires on `break` inside a `switch` that happens to sit inside a `for`,
      // which is exactly the shape of the fold in `src/turns.ts`. Extracting
      // the switch into a function to satisfy it would make that fold harder
      // to read, not easier.
      'unicorn/no-break-in-nested-loop': 'off',

      // Wants every one-line `/** ... */` expanded to three lines. The concise
      // form is used deliberately for short field notes.
      'unicorn/single-line-block-comment-style': 'off',

      // Both prefer a shape this codebase chose against: an early return for
      // the uninteresting case, then the body unindented.
      'unicorn/prefer-ternary': 'off',
      'unicorn/prefer-early-return': 'off',

      // Browser-only app. `window.location` says where it runs; `globalThis`
      // is for code that has to work in both.
      'unicorn/prefer-global-this': 'off',

      // `getElementById` is not worse than `querySelector('#id')`.
      'unicorn/prefer-query-selector': 'off',

      // `reduce` is the right tool for `lastSeq`, and this rule is contentious
      // enough that it should not be decided by a default.
      'unicorn/no-array-reduce': 'off',

      // `[...map.values()].sort(...)` already sorts a fresh array, so the
      // mutation these warn about cannot happen. `toSorted` and
      // `Iterator.toArray` buy nothing here.
      'unicorn/no-array-sort': 'off',
      'unicorn/prefer-iterator-to-array': 'off',

      // The module-level `provider` in `src/api/auth.ts` IS the seam — one
      // mutable slot a host app fills at startup. That is the documented design.
      'unicorn/no-top-level-assignment-in-function': 'off',

      // `response.json().catch(() => null)` is clearer than the try/await form
      // for "parse it if you can, otherwise nothing".
      'unicorn/prefer-await': 'off',

      // The two guards in the reattach effect are separate because they are
      // separate reasons, each with its own comment, and the second reads a
      // field the first proves is there. Merging them with `||` loses both.
      'unicorn/prefer-simple-condition-first': 'off',
      'unicorn/prefer-combined-guards': 'off',

      // ---- unicorn: configured rather than disabled ----------------------

      // Enforces the CONVENTIONS.md naming rule instead of unicorn's kebab-case
      // default: `Bubble.tsx` for a component, `useConversationStream.ts` for
      // a hook, `turns.ts` for a module.
      'unicorn/filename-case': ['error', { cases: { camelCase: true, pascalCase: true } }],

      // `caught`, not `error` — there is already an `error` in scope in the
      // places this matters, and shadowing it is how you log the wrong one.
      'unicorn/catch-error-name': ['error', { name: 'caught' }],
    },
  },

  {
    files: ['**/*.tsx'],
    extends: [jsxA11y.flatConfigs.strict],
    plugins: { react, 'react-refresh': reactRefresh },
    settings: { react: { version: '19.0' } },
    rules: {
      // `<Bubble role={'assistant'}>` is the chat domain's `role` — the same
      // one the backend puts on a message — not an ARIA role. Checking real
      // DOM elements only is what this option is for; `role="alert"` on the
      // error banner is still verified.
      'jsx-a11y/aria-role': ['error', { ignoreNonDOM: true }],

      // The other half of "never enable raw HTML". Banning the import is not
      // enough on its own: `dangerouslySetInnerHTML` needs no dependency, and
      // the one place model output becomes DOM is exactly where someone would
      // reach for it to fix a rendering edge case.
      'react/no-danger': 'error',

      // "One component per file, default export, named to match the file."
      //
      // This is the rule that actually checks it, and it is the reason the
      // linter exists: `react-refresh/only-export-components` looks only at
      // what a file EXPORTS, so it was perfectly happy with a MessageList.tsx
      // that defined three components and exported one. `no-multi-comp` counts
      // definitions, which is the thing the doc was really asking for.
      'react/no-multi-comp': ['error', { ignoreStateless: false }],

      // A component file exports its component and nothing else. A helper that
      // a second file wants belongs in a .ts module, where importing it does
      // not drag a component along behind it.
      'react-refresh/only-export-components': ['error', { allowConstantExport: false }],
    },
  },

  reactHooks.configs.flat.recommended,

  // Build files run in Node and are not part of the browser program.
  {
    files: ['vite.config.ts', 'eslint.config.js'],
    languageOptions: { globals: globals.node },
    rules: { 'no-restricted-imports': 'off' },
  },
  { files: ['**/*.js'], extends: [tseslint.configs.disableTypeChecked] },

  // Last: turns off everything Prettier owns, so formatting is never two tools'
  // opinion at once.
  prettier,
);
