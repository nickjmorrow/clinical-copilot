/**
 * Small style tokens shared by every form-shaped control — a text input, a
 * select, a field label. Copy-pasted byte-for-byte into eight different
 * files before this existed (`DefinitionForm.tsx`, `PredicateEditor.tsx`,
 * `DimensionEditor.tsx`, `MeasureEditor.tsx`, `AgeBandListInput.tsx`,
 * `StringListInput.tsx`, `SavedQuestionForm.tsx`, `AccessPanel.tsx`), with
 * no drift between any of them — which is the one thing worth preserving
 * here: one definition instead of eight identical ones is a lower bar to
 * trip over the next time one of them needs to change.
 *
 * No React import, so this lives at the top level rather than in
 * `components/` — the same reason `turns.ts`/`format.ts` do. See CONVENTIONS.md
 * > Layout.
 */

export const INPUT =
  'w-full rounded-lg border border-ink/10 bg-surface px-2.5 py-1.5 text-xs text-ink outline-none focus:border-accent/50 focus:ring-2 focus:ring-accent/15';

export const LABEL = 'text-[11px] font-semibold tracking-wide text-ink-muted uppercase';

/** A group heading inside the sidebar — "Curate", "Pinned", "Filters". Smaller
 *  and lighter than `LABEL`, because it labels a run of links rather than a
 *  field someone is about to fill in. */
export const SIDEBAR_HEADING =
  'px-2.5 pt-3 pb-1 text-[10px] font-medium tracking-wide text-ink-muted uppercase';
