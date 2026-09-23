import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { errorMessage } from 'src/api/client';
import { fetchClinicalContext } from 'src/api/clinical';
import Button from 'src/components/Button';
import Page from 'src/components/Page';
import TermCheckboxGroup from 'src/components/TermCheckboxGroup';
import useSavedQuestionActions from 'src/hooks/useSavedQuestionActions';
import { INPUT, LABEL } from 'src/styles';

interface Props {
  onCreated: (id: string) => void;
}

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

/**
 * A new saved question: a name, at least one filter, and optionally measures
 * and a group-by. Built from the real vocabulary — the same `/clinical/
 * context` the chat panel shows — via `TermCheckboxGroup`, so there is no way
 * to save a term name that will not resolve.
 */
export default function SavedQuestionForm({ onCreated }: Props) {
  const context = useQuery({
    queryFn: () => fetchClinicalContext(),
    queryKey: ['clinical', 'context'],
  });
  const actions = useSavedQuestionActions();

  const [name, setName] = useState('');
  const [terms, setTerms] = useState<string[]>([]);
  const [measures, setMeasures] = useState<string[]>([]);
  const [groupBy, setGroupBy] = useState<string[]>([]);
  const [formError, setFormError] = useState<null | string>(null);

  if (context.error) {
    return <p className={'p-4 text-xs text-danger'}>Could not load the vocabulary.</p>;
  }

  const allTerms = context.data?.terms ?? [];
  const filters = allTerms.filter((t) => t.kind === 'filter');
  const measureTerms = allTerms.filter((t) => t.kind === 'measure');
  const dimensionTerms = allTerms.filter((t) => t.kind === 'dimension');

  const save = async () => {
    setFormError(null);
    if (!name.trim()) {
      setFormError('Give it a name.');
      return;
    }
    if (terms.length === 0) {
      setFormError('Pick at least one filter — a saved question always narrows to a population.');
      return;
    }
    try {
      const created = await actions.create({ groupBy, measures, name, terms });
      setName('');
      setTerms([]);
      setMeasures([]);
      setGroupBy([]);
      onCreated(created.id);
    } catch (caught) {
      setFormError(errorMessage(caught));
    }
  };

  return (
    <Page title={'New saved question'} width={'form'}>
      <label className={'flex flex-col gap-1'}>
        <span className={LABEL}>Name</span>
        <input
          className={INPUT}
          onChange={(event) => {
            setName(event.target.value);
          }}
          placeholder={'Elderly on a high-risk nephrotoxin'}
          value={name}
        />
      </label>

      <TermCheckboxGroup
        label={'Filters (combined with AND)'}
        onChange={(term) => {
          setTerms((current) => toggle(current, term));
        }}
        selected={terms}
        terms={filters}
      />

      <TermCheckboxGroup
        label={'Measures — leave empty for a plain patient list'}
        onChange={(term) => {
          setMeasures((current) => toggle(current, term));
        }}
        selected={measures}
        terms={measureTerms}
      />

      {measures.length > 0 && (
        <TermCheckboxGroup
          label={'Group by'}
          onChange={(term) => {
            setGroupBy((current) => toggle(current, term));
          }}
          selected={groupBy}
          terms={dimensionTerms}
        />
      )}

      {formError && <p className={'text-xs text-danger'}>{formError}</p>}

      <Button
        className={'self-start'}
        disabled={actions.isBusy}
        onClick={() => void save()}
        variant={'primary'}
      >
        Save question
      </Button>
    </Page>
  );
}
