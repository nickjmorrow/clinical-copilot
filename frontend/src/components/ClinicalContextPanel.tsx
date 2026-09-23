import { useQuery } from '@tanstack/react-query';
import { errorMessage } from 'src/api/client';
import { fetchClinicalContext } from 'src/api/clinical';
import InlineError from 'src/components/InlineError';
import TermGroup from 'src/components/TermGroup';
import { formatDate } from 'src/format';

// The catalog can run into the hundreds of codes — Synthea's full export
// tracks far more than the definitions layer names — so the glance view
// shows a sample rather than every one, with the rest behind a disclosure.
const SAMPLE_CATALOG_SIZE = 6;

interface Props {
  /** Close the panel. Offered inside it, for when it is a drawer over the
   *  chat on a narrow window and the header's toggle is underneath it. */
  onClose: () => void;
  /** Put a term into the question being written. */
  onPickTerm: (term: string) => void;
}

/**
 * What this app understands, and what it holds.
 *
 * The definitions layer is the whole architecture, and without something like
 * this it is invisible: a blank text box gives a reader no way to know whether
 * "frailty" is a concept the system has. The model can explain the vocabulary
 * when asked — it is in the system prompt — but that requires knowing to ask,
 * and costs a round trip to find out the system cannot help.
 *
 * Served from `/clinical/context`, which reads the same `clinical_definitions`
 * rows the query layer resolves against. A hard-coded list here would be a
 * second copy of the vocabulary, wrong the first time a definition changed.
 *
 * `why` is rendered because a threshold a reader cannot interrogate is one
 * they have to take on trust. The predicate itself is deliberately not in the
 * payload at all.
 *
 * Every term is clickable and drops itself into the message box: the panel
 * answers "what can I ask?", and the next thing anyone does with the answer
 * is ask.
 */
export default function ClinicalContextPanel({ onClose, onPickTerm }: Props) {
  const { data, error, isPending, refetch } = useQuery({
    queryFn: ({ signal }) => fetchClinicalContext(signal),
    queryKey: ['clinical', 'context'],
    // Definitions change when a person edits them, which is approximately
    // never during a session.
    staleTime: 5 * 60 * 1000,
  });

  if (isPending) {
    return <p className={'p-4 text-xs text-ink-muted'}>Loading…</p>;
  }

  if (error) {
    return (
      <div className={'p-4'}>
        <InlineError
          message={`Could not load the clinical terms. ${errorMessage(error)}`}
          onRetry={() => void refetch()}
        />
      </div>
    );
  }

  const { dataset, terms } = data;
  const filters = terms.filter((term) => term.kind === 'filter');
  const measures = terms.filter((term) => term.kind === 'measure');
  const dimensions = terms.filter((term) => term.kind === 'dimension');

  return (
    <div className={'flex h-full flex-col overflow-y-auto'}>
      <div className={'border-b border-ink/5 px-4 py-3'}>
        <div className={'flex items-center justify-between gap-2'}>
          <h2 className={'text-sm font-semibold tracking-tight text-ink'}>What you can ask</h2>
          <button
            aria-label={'Close'}
            className={
              'rounded-md px-1.5 text-base leading-none text-ink-muted hover:text-ink lg:hidden'
            }
            onClick={onClose}
            type={'button'}
          >
            ×
          </button>
        </div>
        <p className={'mt-1 text-xs text-ink-muted'}>
          {filters.length} filter{filters.length === 1 ? '' : 's'} to narrow a question,{' '}
          {measures.length} measure{measures.length === 1 ? '' : 's'} to aggregate, and{' '}
          {dimensions.length} way{dimensions.length === 1 ? '' : 's'} to group by. Filters combine
          with AND. Click a term to add it to your question.
        </p>
      </div>

      <TermGroup label={'Filters'} onPick={onPickTerm} terms={filters} />
      <TermGroup label={'Measures'} onPick={onPickTerm} terms={measures} />
      <TermGroup label={'Group by'} onPick={onPickTerm} terms={dimensions} />

      <div className={'mt-auto border-t border-ink/5 px-4 py-3'}>
        <h3 className={'text-xs font-semibold tracking-tight text-ink'}>In this dataset</h3>
        {dataset.dataset && (
          <p className={'mt-2 text-[11px] leading-relaxed text-ink-muted'}>
            {dataset.dataset.source}, as of {formatDate(dataset.dataset.asOfDate)}. Every age and
            every "currently prescribed" in an answer is relative to that date, not today.
          </p>
        )}
        <dl className={'mt-2 flex flex-col gap-1 text-[11px] text-ink-muted'}>
          <div className={'flex justify-between gap-2'}>
            <dt>Patients</dt>
            <dd className={'text-ink'}>{dataset.patients.toLocaleString()}</dd>
          </div>
          <div className={'flex justify-between gap-2'}>
            <dt>Medications</dt>
            <dd className={'text-ink'}>{dataset.medications.toLocaleString()}</dd>
          </div>
          <div className={'flex justify-between gap-2'}>
            <dt>Prescriptions</dt>
            <dd className={'text-ink'}>{dataset.prescriptions.toLocaleString()}</dd>
          </div>
          <div className={'flex justify-between gap-2'}>
            <dt>Observations</dt>
            <dd className={'text-ink'}>{dataset.observations.toLocaleString()}</dd>
          </div>
          <div className={'mt-1 flex flex-col gap-0.5'}>
            <dt>Measurements tracked</dt>
            <dd className={'text-ink'}>
              {dataset.observationCatalog.length.toLocaleString()} kinds, including{' '}
              {dataset.observationCatalog
                .slice(0, SAMPLE_CATALOG_SIZE)
                .map((entry) => entry.display)
                .join(', ')}
              {dataset.observationCatalog.length > SAMPLE_CATALOG_SIZE && (
                <details className={'group mt-1 inline'}>
                  <summary
                    className={'inline cursor-pointer text-[11px] text-ink-muted hover:text-ink'}
                  >
                    …and{' '}
                    {(dataset.observationCatalog.length - SAMPLE_CATALOG_SIZE).toLocaleString()}{' '}
                    more
                  </summary>
                  <p className={'mt-1 leading-relaxed'}>
                    {dataset.observationCatalog
                      .slice(SAMPLE_CATALOG_SIZE)
                      .map((entry) => entry.display)
                      .join(', ')}
                  </p>
                </details>
              )}
            </dd>
          </div>
          {Object.entries(dataset.annotationValues).map(([attribute, values]) => (
            <div className={'mt-1 flex flex-col gap-0.5'} key={attribute}>
              <dt>{attribute.replaceAll('_', ' ')} tiers</dt>
              <dd className={'text-ink'}>{values.join(', ')}</dd>
            </div>
          ))}
          <div className={'mt-1 flex flex-col gap-0.5'}>
            <dt>Returned per patient</dt>
            <dd className={'text-ink'}>{dataset.returnableColumns.join(', ')}</dd>
          </div>
          <div className={'mt-1 flex flex-col gap-0.5'}>
            {/* Shown rather than hidden: a reader who knows names are
                unavailable asks a different question, and one who does not
                assumes the tool is broken. */}
            <dt>Never returned</dt>
            <dd className={'text-ink'}>{dataset.restrictedColumns.join(', ')}</dd>
          </div>
        </dl>
        <p className={'mt-3 text-[11px] leading-relaxed text-ink-muted'}>
          All synthetic. A demonstration, not a clinical decision support tool.
        </p>
      </div>
    </div>
  );
}
