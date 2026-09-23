import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import { errorMessage } from 'src/api/client';
import { downloadCohortCsv, runCohortQuery } from 'src/api/cohort';
import { type CohortCall, type CohortOutcome, cohortQuery } from 'src/cohortCall';
import Button from 'src/components/Button';
import RowTable from 'src/components/RowTable';
import SaveQuestionPrompt from 'src/components/SaveQuestionPrompt';

interface Props {
  call: CohortCall;
  outcome: CohortOutcome;
}

/**
 * What you can do with a chat answer, under the answer: see the patients
 * behind it, take it away as a CSV, or keep the question.
 *
 * These used to sit inside the collapsed tool card, below the raw JSON
 * arguments — the most useful things on screen, behind the least inviting
 * click. They are the reason a clinician asked, so they are visible by
 * default; the arguments and the SQL are what is collapsed now.
 *
 * "Show patients" is for a patient list only. An aggregate's rows are the
 * groups in the chart; the patients inside each group are a different
 * question, and offering them here would blur the two.
 */
export default function AnswerActions({ call, outcome }: Props) {
  const query = cohortQuery(call, outcome);
  const roster = useMutation({ mutationFn: () => runCohortQuery(query) });
  const exportCsv = useMutation({ mutationFn: () => downloadCohortCsv(query) });
  const [isSaving, setIsSaving] = useState(false);

  return (
    <div className={'flex flex-col gap-2'}>
      <div className={'flex flex-wrap gap-2'}>
        {!outcome.aggregate && !roster.data && (
          <Button disabled={roster.isPending} onClick={() => roster.mutate()} size={'sm'}>
            {roster.isPending ? 'Loading…' : 'Show patients'}
          </Button>
        )}
        <Button disabled={exportCsv.isPending} onClick={() => exportCsv.mutate()} size={'sm'}>
          {exportCsv.isPending ? 'Preparing…' : 'Download CSV'}
        </Button>
        {!isSaving && (
          <Button
            onClick={() => {
              setIsSaving(true);
            }}
            size={'sm'}
          >
            Save question
          </Button>
        )}
      </div>

      {roster.error && <p className={'text-danger'}>{errorMessage(roster.error)}</p>}
      {exportCsv.error && <p className={'text-danger'}>{errorMessage(exportCsv.error)}</p>}

      {isSaving && (
        <SaveQuestionPrompt
          call={call}
          onCancel={() => {
            setIsSaving(false);
          }}
        />
      )}

      {roster.data && (
        <div className={'flex flex-col gap-1'}>
          <p className={'text-ink-muted'}>
            {roster.data.rowCount.toLocaleString()} patient
            {roster.data.rowCount === 1 ? '' : 's'}, every returnable column
          </p>
          {/* Capped, with its own scroll: a hundred rows inline would push
              the answer they belong to off the screen. */}
          <div className={'max-h-80 overflow-y-auto'}>
            <RowTable columns={roster.data.columns} rows={roster.data.rows} />
          </div>
        </div>
      )}
    </div>
  );
}
