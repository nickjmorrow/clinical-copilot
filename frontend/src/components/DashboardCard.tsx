import { useQuery } from '@tanstack/react-query';
import { errorMessage } from 'src/api/client';
import type { SavedQuestion } from 'src/api/savedQuestions';
import { runSavedQuestion } from 'src/api/savedQuestions';
import InlineError from 'src/components/InlineError';
import SavedQuestionResult from 'src/components/SavedQuestionResult';
import { describeQuestion } from 'src/format';

interface Props {
  question: SavedQuestion;
}

/**
 * One saved question's current answer, as a dashboard tile.
 *
 * Runs on mount rather than on request — the whole point of a dashboard is
 * seeing every result at a glance without a click per question — and, like
 * every other saved-question run, re-asks the definitions layer fresh: there
 * is no cached answer to serve here, only a cached *request* (TanStack's own
 * default `staleTime` of 0 already refetches on every mount, so switching to
 * the dashboard and back always shows a current answer, not the one from
 * five minutes ago).
 */
export default function DashboardCard({ question }: Props) {
  const run = useQuery({
    queryFn: () => runSavedQuestion(question.id),
    queryKey: ['savedQuestions', question.id, 'run'],
  });

  return (
    <div className={'rounded-xl border border-ink/10 bg-surface-raised p-4'}>
      <div className={'mb-3'}>
        <h3 className={'text-sm font-semibold tracking-tight text-ink'}>{question.name}</h3>
        <p className={'mt-0.5 text-xs text-ink-muted'}>{describeQuestion(question)}</p>
      </div>

      {run.isPending && <p className={'text-xs text-ink-muted'}>Running…</p>}
      {run.error && (
        <InlineError
          message={`Could not run this question. ${errorMessage(run.error)}`}
          onRetry={() => void run.refetch()}
        />
      )}
      {run.data && <SavedQuestionResult result={run.data} />}
    </div>
  );
}
