import { useState } from 'react';
import { toChartData } from 'src/chart';
import { describeOutcome, readCohortCall, readCohortOutcome } from 'src/cohortCall';
import AnswerActions from 'src/components/AnswerActions';
import Chart from 'src/components/Chart';
import { describeQuestion, formatDuration, summarizeToolInput } from 'src/format';

interface Props {
  /** The structured half of the result: a count, and rows for a chart. Null
   *  when no query ran — a clarification or a refusal. */
  data: Record<string, unknown> | null;
  /** How long the call took, or null while it is still running. */
  durationMs: null | number;
  input: Record<string, unknown>;
  isError: boolean;
  name: string;
  result: null | string;
}

/**
 * One tool call, shown to the user — in two layers.
 *
 * **The result, open.** For a question about patients: what was asked, in the
 * vocabulary's words; how many matched; the chart, for an aggregate; and what
 * you can do with it next. That is what the person asked for, so it is on
 * screen without a click. It used to be the other way round — a collapsed
 * card headed `find_patients terms: [...] columns: []`, with the chart and
 * the export buried under the raw JSON.
 *
 * **How it was answered, collapsed.** The arguments the model passed and the
 * full result it read back: the definitions applied and the SQL executed.
 * Deliberately not hidden — a tool call nobody can inspect is the reason
 * people distrust these apps — but it is the audit trail, not the answer, and
 * a transcript that spends a screen on it buries what it was for.
 *
 * A FAILURE opens the details itself, because then the detail is the point.
 * The open state is derived from `isError` with an override rather than
 * synchronised to it (the same shape as `ThinkingBlock`), so a result arriving
 * after the reader has collapsed the card cannot yank it back open.
 */
export default function ToolCard({ data, durationMs, input, isError, name, result }: Props) {
  const [override, setOverride] = useState<null | boolean>(null);
  const isOpen = override ?? isError;
  const isRunning = result === null;

  const call = readCohortCall(name, input);
  const outcome = isError ? null : readCohortOutcome(data);
  const chart = outcome?.aggregate ? toChartData(data) : null;

  // Only a finished, successful call with no data ran no query at all.
  const status = isRunning
    ? 'running…'
    : isError
      ? 'failed'
      : call && !outcome
        ? 'no query run'
        : null;

  return (
    <div
      className={[
        'w-full max-w-full min-w-0 overflow-hidden rounded-xl border text-xs',
        isError ? 'border-danger/30 bg-danger/5' : 'border-ink/10 bg-surface-raised',
      ].join(' ')}
    >
      <div className={'flex items-baseline gap-2 px-3 py-2'}>
        {call ? (
          <>
            <span className={'shrink-0 font-medium text-ink'}>Searched patients</span>
            <span className={'min-w-0 flex-1 truncate text-ink-muted'}>
              {describeQuestion(call)}
            </span>
          </>
        ) : (
          <>
            <span className={'shrink-0 font-mono font-medium text-ink'}>{name}</span>
            <span className={'min-w-0 flex-1 truncate font-mono text-ink-muted'}>
              {summarizeToolInput(input)}
            </span>
          </>
        )}
        <span
          className={[
            'shrink-0 tabular-nums',
            isError ? 'font-medium text-danger' : 'text-ink-muted',
            isRunning ? 'animate-pulse' : '',
          ]
            .filter(Boolean)
            .join(' ')}
        >
          {status}
          {/* Both can show: a call that failed still took time worth seeing. */}
          {durationMs !== null && `${status ? ' · ' : ''}${formatDuration(durationMs)}`}
        </span>
      </div>

      {call && outcome && (
        <div className={'flex flex-col gap-3 border-t border-ink/10 px-3 py-2.5'}>
          <p className={'text-sm font-medium text-ink'}>{describeOutcome(outcome)}</p>
          {chart && <Chart data={chart} />}
          <AnswerActions call={call} outcome={outcome} />
        </div>
      )}

      <button
        aria-expanded={isOpen}
        className={
          'flex w-full items-center gap-1.5 border-t border-ink/10 px-3 py-1.5 text-left text-ink-muted transition hover:bg-ink/5 hover:text-ink'
        }
        onClick={() => {
          setOverride(!isOpen);
        }}
        type={'button'}
      >
        <svg
          aria-hidden={'true'}
          className={['h-3 w-3 shrink-0 transition', isOpen && 'rotate-90']
            .filter(Boolean)
            .join(' ')}
          fill={'none'}
          stroke={'currentColor'}
          strokeLinecap={'round'}
          strokeLinejoin={'round'}
          strokeWidth={2}
          viewBox={'0 0 24 24'}
        >
          <polyline points={'9 18 15 12 9 6'} />
        </svg>
        {call ? 'How this was answered' : 'Details'}
      </button>

      {isOpen && (
        <div className={'border-t border-ink/10 px-3 py-2'}>
          <p className={'mb-1 font-medium text-ink-muted'}>Arguments</p>
          <pre className={'overflow-x-auto font-mono text-ink'}>
            {JSON.stringify(input, null, 2)}
          </pre>

          <p className={'mt-3 mb-1 font-medium text-ink-muted'}>
            {call ? 'Definitions applied, and the SQL that ran' : 'Result'}
          </p>
          <pre
            className={[
              'overflow-x-auto font-mono whitespace-pre-wrap',
              isError ? 'text-danger' : 'text-ink',
            ].join(' ')}
          >
            {result ?? 'Still running.'}
          </pre>
        </div>
      )}
    </div>
  );
}
