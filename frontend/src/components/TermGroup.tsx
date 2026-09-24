/**
 * One kind of term (filter, measure, or group-by), as a labelled list.
 *
 * Split out of `ClinicalContextPanel` rather than kept as a second component
 * in that file — AGENTS.md > Layout: one component per file, named after
 * what it exports.
 */

interface Term {
  term: string;
  means: string;
  alsoCalled: string[];
  why: string;
}

interface TermGroupProps {
  label: string;
  /** Put a term into the question being written. */
  onPick: (term: string) => void;
  terms: Term[];
}

export default function TermGroup({ label, onPick, terms }: TermGroupProps) {
  if (terms.length === 0) return null;

  return (
    <div className={'border-b border-ink/5 px-4 py-3'}>
      <h3 className={'text-[11px] font-semibold tracking-wide text-ink-muted uppercase'}>
        {label}
      </h3>
      <ul className={'mt-2 flex flex-col gap-3'}>
        {terms.map((term) => (
          <li key={term.term}>
            {/* A button, because reading a term and then retyping it into
                the box below is the step this panel exists to save. */}
            <button
              className={
                'text-left text-xs font-medium text-ink underline-offset-2 hover:text-accent hover:underline'
              }
              onClick={() => {
                onPick(term.term);
              }}
              title={'Add to your question'}
              type={'button'}
            >
              {term.term}
            </button>
            <p className={'mt-0.5 text-xs text-ink-muted'}>{term.means}</p>
            {term.alsoCalled.length > 0 && (
              <p className={'mt-1 text-[11px] text-ink-muted'}>
                also: {term.alsoCalled.join(', ')}
              </p>
            )}
            <details className={'group mt-1'}>
              <summary className={'cursor-pointer text-[11px] text-ink-muted hover:text-ink'}>
                why
              </summary>
              <p className={'mt-1 text-[11px] leading-relaxed text-ink-muted'}>{term.why}</p>
            </details>
          </li>
        ))}
      </ul>
    </div>
  );
}
