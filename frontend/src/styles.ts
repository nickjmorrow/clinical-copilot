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
 * `components/` — the same reason `turns.ts`/`format.ts` do. See AGENTS.md
 * > Layout.
 */

// `disabled:` keeps the text at full strength: a read-only definition is still
// something to read, and browsers grey disabled controls out by default —
// Safari through `-webkit-text-fill-color`, which `color` alone does not reach.
export const INPUT =
  'w-full rounded-lg border border-ink/10 bg-surface px-2.5 py-1.5 text-xs text-ink outline-none focus:border-accent/50 focus:ring-2 focus:ring-accent/15 disabled:cursor-default disabled:border-ink/5 disabled:opacity-100 disabled:[-webkit-text-fill-color:currentColor]';

export const LABEL = 'text-[11px] font-semibold tracking-wide text-ink-muted uppercase';

/** A group heading inside the sidebar — "Curate", "Pinned", "Filters". Smaller
 *  and lighter than `LABEL`, because it labels a run of links rather than a
 *  field someone is about to fill in. */
export const SIDEBAR_HEADING =
  'px-2.5 pt-3 pb-1 text-[10px] font-medium tracking-wide text-ink-muted uppercase';

// For a control that only means something while editing — "+ Add condition",
// "Remove". Inside a disabled fieldset, which is how `DefinitionForm` shows a
// definition read-only, it is hidden rather than greyed out: a button nobody
// can press is noise in something that is there to be read.
export const EDIT_ONLY = '[fieldset:disabled_&]:hidden';
