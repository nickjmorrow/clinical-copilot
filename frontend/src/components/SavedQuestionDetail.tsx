import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import { errorMessage } from 'src/api/client';
import { runSavedQuestion, type SavedQuestion } from 'src/api/savedQuestions';
import Button from 'src/components/Button';
import SavedQuestionResult from 'src/components/SavedQuestionResult';
import { describeQuestion } from 'src/format';
import useSavedQuestionActions from 'src/hooks/useSavedQuestionActions';

interface Props {
  onDeleted: () => void;
  question: SavedQuestion;
}

/**
 * One saved question: what it asks, a Run button, and the result of the most
 * recent run — never a stored one. Re-running goes through the real
 * definitions layer every time (`POST /saved-questions/{id}/run`), which is
 * why there is no "last run" timestamp here: showing one would imply the
 * result is cached, and it never is.
 *
 * Keyed by `question.id` in the parent, so switching which question is
 * selected clears the previous run instead of an effect syncing it away.
 */
export default function SavedQuestionDetail({ onDeleted, question }: Props) {
  const actions = useSavedQuestionActions();
  // A `useMutation` directly, not another wrapper through the shared hook —
  // `run` has exactly one caller (this component), and `question.id` is
  // already fixed for the lifetime of this instance (`App` keys the panel by
  // it), so `mutationFn` closing over it needs no parameter passed at call
  // time.
  const run = useMutation({ mutationFn: () => runSavedQuestion(question.id) });
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);
  const [deletionError, setDeletionError] = useState<null | string>(null);

  const remove = async () => {
    if (!isConfirmingDelete) {
      setIsConfirmingDelete(true);
      return;
    }
    setDeletionError(null);
    try {
      await actions.remove(question.id);
      onDeleted();
    } catch (caught) {
      setDeletionError(errorMessage(caught));
      setIsConfirmingDelete(false);
    }
  };

  return (
    <div className={'flex h-full flex-col overflow-y-auto px-6 py-5'}>
      <div className={'flex items-start justify-between gap-3'}>
        <div>
          <h2 className={'text-sm font-semibold tracking-tight text-ink'}>{question.name}</h2>
          <p className={'mt-1 text-xs text-ink-muted'}>{describeQuestion(question)}</p>
        </div>
        <Button
          className={'shrink-0'}
          danger={isConfirmingDelete}
          onClick={() => void remove()}
          size={'sm'}
        >
          {isConfirmingDelete ? 'Really delete?' : 'Delete'}
        </Button>
      </div>

      {deletionError && <p className={'mt-2 text-xs text-danger'}>{deletionError}</p>}

      <Button
        className={'mt-4 self-start'}
        disabled={run.isPending}
        onClick={() => run.mutate()}
        variant={'primary'}
      >
        {run.isPending ? 'Running…' : 'Run'}
      </Button>

      {run.error && <p className={'mt-3 text-xs text-danger'}>{errorMessage(run.error)}</p>}

      {run.data && (
        <div className={'mt-4'}>
          <SavedQuestionResult result={run.data} />
        </div>
      )}
    </div>
  );
}
