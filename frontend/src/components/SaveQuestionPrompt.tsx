import { useState } from 'react';
import { Link } from 'react-router';
import { errorMessage } from 'src/api/client';
import type { CohortCall } from 'src/cohortCall';
import Button from 'src/components/Button';
import useSavedQuestionActions from 'src/hooks/useSavedQuestionActions';
import { paths } from 'src/paths';
import { INPUT } from 'src/styles';

interface Props {
  call: CohortCall;
  onCancel: () => void;
}

// Long enough for most questions as typed; a paragraph is not a name.
const NAME_LENGTH = 80;

function suggestedName(question: string): string {
  const trimmed = question.trim();
  return trimmed.length > NAME_LENGTH ? `${trimmed.slice(0, NAME_LENGTH - 1)}…` : trimmed;
}

/**
 * Save a chat answer's question, from the answer.
 *
 * The question is already structured — the model chose defined terms,
 * measures and dimensions to answer it — so saving asks for nothing but a
 * name, pre-filled with the question as it was typed. Before this, keeping a
 * question you had just asked meant rebuilding it from checkboxes on another
 * screen.
 *
 * What is saved is the terms, not the answer: running it later re-asks the
 * definitions layer, so an edited threshold changes the result, the same as
 * asking again in chat.
 */
export default function SaveQuestionPrompt({ call, onCancel }: Props) {
  const actions = useSavedQuestionActions();
  const [name, setName] = useState(() => suggestedName(call.question));
  const [savedId, setSavedId] = useState<null | string>(null);
  const [error, setError] = useState<null | string>(null);

  if (savedId !== null) {
    return (
      <p className={'text-ink-muted'}>
        Saved.{' '}
        <Link className={'font-medium text-accent hover:underline'} to={paths.saved(savedId)}>
          Open it in Saved questions
        </Link>
      </p>
    );
  }

  const save = async () => {
    setError(null);
    if (!name.trim()) {
      setError('Give it a name.');
      return;
    }
    try {
      const created = await actions.create({
        groupBy: call.groupBy,
        measures: call.measures,
        name: name.trim(),
        terms: call.terms,
      });
      setSavedId(created.id);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  return (
    <form
      className={'flex flex-col gap-1.5'}
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <label className={'flex items-center gap-2'}>
        <span className={'shrink-0 text-ink-muted'}>Name</span>
        <input
          aria-label={'Saved question name'}
          className={INPUT}
          onChange={(event) => {
            setName(event.target.value);
          }}
          value={name}
        />
      </label>
      <div className={'flex items-center gap-2'}>
        <Button disabled={actions.isBusy} size={'sm'} type={'submit'} variant={'primary'}>
          {actions.isBusy ? 'Saving…' : 'Save'}
        </Button>
        <Button onClick={onCancel} size={'sm'}>
          Cancel
        </Button>
        {error && <p className={'text-danger'}>{error}</p>}
      </div>
    </form>
  );
}
