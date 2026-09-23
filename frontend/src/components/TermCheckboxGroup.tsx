interface Props {
  label: string;
  onChange: (term: string) => void;
  selected: string[];
  terms: { term: string; means: string }[];
}

/**
 * One kind of term (filter, measure, or group-by) as a checkbox list —
 * `SavedQuestionForm`'s way of building `terms`/`measures`/`groupBy` from the
 * real vocabulary in `/clinical/context` rather than free text. A typo in a
 * hand-typed term name would fail only when the question is run; a checkbox
 * list of names that are known to resolve cannot produce that failure at all.
 */
export default function TermCheckboxGroup({ label, onChange, selected, terms }: Props) {
  if (terms.length === 0) return null;

  return (
    <fieldset className={'flex flex-col gap-1'}>
      <legend className={'text-[11px] font-semibold tracking-wide text-ink-muted uppercase'}>
        {label}
      </legend>
      <div className={'flex flex-col gap-1 rounded-lg border border-ink/10 px-2.5 py-2'}>
        {terms.map((term) => (
          <label className={'flex items-start gap-2 text-xs text-ink'} key={term.term}>
            <input
              checked={selected.includes(term.term)}
              className={'mt-0.5'}
              onChange={() => {
                onChange(term.term);
              }}
              type={'checkbox'}
            />
            <span>
              {term.term}
              <span className={'block text-[11px] text-ink-muted'}>{term.means}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
