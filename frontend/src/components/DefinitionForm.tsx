import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { errorMessage } from 'src/api/client';
import {
  type Definition,
  type DefinitionDraft,
  definitionKeys,
  getDefinitionHistory,
  previewDefinition,
} from 'src/api/definitions';
import Button from 'src/components/Button';
import DimensionEditor from 'src/components/DimensionEditor';
import InlineError from 'src/components/InlineError';
import MeasureEditor from 'src/components/MeasureEditor';
import Page from 'src/components/Page';
import PredicateEditor from 'src/components/PredicateEditor';
import { formatDateTime } from 'src/format';
import useDefinitionActions from 'src/hooks/useDefinitionActions';
import {
  type Dimension,
  dimensionFromLogic,
  emptyDimension,
  emptyMeasure,
  emptyPredicate,
  type Measure,
  measureFromLogic,
  type Predicate,
  predicateFromLogic,
} from 'src/predicates';
import { INPUT, LABEL } from 'src/styles';

interface Props {
  definition: Definition | null;
  filterTerms: string[];
  /** Show the definition without any way to change it — for anyone who is
   *  not a curator. The server refuses their writes either way. */
  isReadOnly: boolean;
  onDeleted: () => void;
  onSaved: (id: string) => void;
}

const KINDS: Definition['kind'][] = ['filter', 'measure', 'dimension'];
const ENTITIES: Definition['entity'][] = ['patient', 'medication', 'observation'];
// `published` is deliberately absent: reaching it is the dedicated Publish
// button's job, not a value this dropdown can set directly. Publishing is the
// approval gate: a change goes live only by that deliberate act, with a reason.
const EDITABLE_STATUSES: Definition['status'][] = ['draft', 'deprecated'];

type LogicValue = Dimension | Measure | Predicate;

function logicValueFor(kind: Definition['kind'], logic: Record<string, unknown>): LogicValue {
  if (kind === 'measure') return measureFromLogic(logic);
  if (kind === 'dimension') return dimensionFromLogic(logic);
  return predicateFromLogic(logic);
}

function emptyLogicFor(kind: Definition['kind']): LogicValue {
  if (kind === 'measure') return emptyMeasure('patient_count');
  if (kind === 'dimension') return emptyDimension('patient_column');
  return emptyPredicate('age_threshold');
}

/**
 * Create or edit one definition — term, kind, entity, description, notes,
 * synonyms, and `logic` as structured form controls that fork on `kind` and,
 * for a filter, on the predicate's own `type` — see `PredicateEditor` (the
 * recursive one), `MeasureEditor`, `DimensionEditor`.
 *
 * `logic` is kept here as a typed `LogicValue`, not the raw object the API
 * sends and receives — `predicateFromLogic`/`measureFromLogic`/
 * `dimensionFromLogic` (in `src/predicates.ts`) parse it in, and it is
 * already the right shape to serialize straight back out. Nothing in this
 * component parses JSON text; a malformed row still cannot crash the editor,
 * because those parsers fall back to a fresh default instead of throwing.
 *
 * Keyed by the selection in the parent, so switching which definition is
 * selected remounts this component instead of syncing props into state with
 * an effect — see CONVENTIONS.md > Frontend > "Reset state with a key."
 *
 * **Read-only is the same form, disabled.** One `<fieldset disabled>` reaches
 * every control, including the ones deep inside the logic editors, so a
 * visitor reads a definition in exactly the shape a curator edits it — the
 * logic as structure, not a second, summarised rendering of it that could
 * drift from the first. Everything that writes, or previews against patient
 * data, is left out rather than disabled.
 */
export default function DefinitionForm({
  definition,
  filterTerms,
  isReadOnly,
  onDeleted,
  onSaved,
}: Props) {
  const actions = useDefinitionActions();
  const isNew = definition === null;

  const [term, setTerm] = useState(definition?.term ?? '');
  const [kind, setKind] = useState<Definition['kind']>(definition?.kind ?? 'filter');
  const [entity, setEntity] = useState<Definition['entity']>(definition?.entity ?? 'patient');
  const [description, setDescription] = useState(definition?.description ?? '');
  const [notes, setNotes] = useState(definition?.notes ?? '');
  const [synonymsText, setSynonymsText] = useState(definition?.synonyms.join(', ') ?? '');
  const [status, setStatus] = useState<Definition['status']>(definition?.status ?? 'draft');
  const [logicValue, setLogicValue] = useState<LogicValue>(() =>
    definition ? logicValueFor(definition.kind, definition.logic) : emptyLogicFor('filter'),
  );
  const [changeReason, setChangeReason] = useState('');
  const [formError, setFormError] = useState<null | string>(null);
  const [preview, setPreview] = useState<
    { kind: 'count'; value: null | number } | { kind: 'error'; message: string } | null
  >(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);

  const history = useQuery({
    enabled: !isNew,
    queryFn: () => getDefinitionHistory(definition?.id ?? ''),
    queryKey: definitionKeys.history(definition?.id ?? ''),
  });

  const changeKind = (next: Definition['kind']) => {
    setKind(next);
    setLogicValue(emptyLogicFor(next));
    setPreview(null);
  };

  const runPreview = async () => {
    setFormError(null);
    setIsPreviewing(true);
    try {
      const result = await previewDefinition(
        kind,
        logicValue as unknown as Record<string, unknown>,
      );
      setPreview({ kind: 'count', value: result.patientCount });
    } catch (caught) {
      setPreview({ kind: 'error', message: errorMessage(caught) });
    } finally {
      setIsPreviewing(false);
    }
  };

  const save = async () => {
    setFormError(null);
    if (!changeReason.trim()) {
      setFormError('Say why — every change to the model is recorded with a reason.');
      return;
    }

    const synonyms = synonymsText
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    const logic = logicValue as unknown as Record<string, unknown>;

    try {
      if (isNew) {
        const draft: DefinitionDraft = {
          changeReason,
          description,
          entity,
          kind,
          logic,
          notes,
          status,
          synonyms,
          term,
        };
        const created = await actions.create(draft);
        onSaved(created.id);
      } else {
        const saved = await actions.update(definition.id, {
          changeReason,
          description,
          entity,
          kind,
          logic,
          notes,
          status,
          synonyms,
        });
        onSaved(saved.id);
      }
      setChangeReason('');
    } catch (caught) {
      setFormError(errorMessage(caught));
    }
  };

  const publish = async () => {
    if (isNew || !changeReason.trim()) {
      setFormError('Say why you are publishing this — the reason is what makes it reviewed.');
      return;
    }
    setFormError(null);
    try {
      const published = await actions.publish(definition.id, changeReason);
      onSaved(published.id);
      setChangeReason('');
    } catch (caught) {
      setFormError(errorMessage(caught));
    }
  };

  const remove = async () => {
    if (isNew) return;
    if (!isConfirmingDelete) {
      setIsConfirmingDelete(true);
      return;
    }
    if (!changeReason.trim()) {
      setFormError('Say why this is being removed.');
      setIsConfirmingDelete(false);
      return;
    }
    setFormError(null);
    try {
      await actions.remove(definition.id, changeReason);
      onDeleted();
    } catch (caught) {
      setFormError(errorMessage(caught));
      setIsConfirmingDelete(false);
    }
  };

  return (
    <Page
      description={
        isNew
          ? undefined
          : `version ${String(definition.version)} · ${definition.status} · last updated by ${definition.updatedBy ?? 'unknown'}`
      }
      title={isNew ? 'New definition' : definition.term}
      width={'form'}
    >
      {isReadOnly && (
        <p className={'rounded-lg bg-ink/5 px-3 py-2 text-xs text-ink-muted'}>
          Read-only. This is exactly what the app applies when a question uses this term; changing
          it needs the curator role.
        </p>
      )}

      <fieldset className={'flex min-w-0 flex-col gap-3'} disabled={isReadOnly}>
        <label className={'flex flex-col gap-1'}>
          <span className={LABEL}>Term</span>
          {isNew ? (
            <input
              className={INPUT}
              onChange={(event) => {
                setTerm(event.target.value);
              }}
              value={term}
            />
          ) : (
            // Immutable after creation — `definition_service.update_definition`
            // has no `term` parameter, deliberately: renaming a term out from
            // under a conversation that already cited it is a different kind of
            // change than editing what it means.
            <p className={'rounded-lg bg-ink/5 px-2.5 py-1.5 text-xs text-ink-muted'}>{term}</p>
          )}
        </label>

        <div className={'grid grid-cols-2 gap-3'}>
          <label className={'flex flex-col gap-1'}>
            <span className={LABEL}>Kind</span>
            <select
              className={INPUT}
              onChange={(event) => {
                changeKind(event.target.value as Definition['kind']);
              }}
              value={kind}
            >
              {KINDS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <label className={'flex flex-col gap-1'}>
            <span className={LABEL}>Entity</span>
            <select
              className={INPUT}
              onChange={(event) => {
                setEntity(event.target.value as Definition['entity']);
              }}
              value={entity}
            >
              {ENTITIES.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className={'flex flex-col gap-1'}>
          <span className={LABEL}>Description</span>
          <input
            className={INPUT}
            onChange={(event) => {
              setDescription(event.target.value);
            }}
            placeholder={'Aged 65 or over.'}
            value={description}
          />
        </label>

        <label className={'flex flex-col gap-1'}>
          <span className={LABEL}>Notes — the rationale</span>
          <textarea
            className={[INPUT, 'min-h-16 resize-y'].join(' ')}
            onChange={(event) => {
              setNotes(event.target.value);
            }}
            placeholder={'Why this threshold, and its source.'}
            value={notes}
          />
        </label>

        <label className={'flex flex-col gap-1'}>
          <span className={LABEL}>Synonyms — comma-separated</span>
          <input
            className={INPUT}
            onChange={(event) => {
              setSynonymsText(event.target.value);
            }}
            placeholder={'older patients, geriatric, seniors'}
            value={synonymsText}
          />
        </label>

        <label className={'flex flex-col gap-1'}>
          <span className={LABEL}>Status</span>
          <select
            className={INPUT}
            onChange={(event) => {
              setStatus(event.target.value as Definition['status']);
            }}
            value={status}
          >
            {EDITABLE_STATUSES.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
            {status === 'published' && <option value={'published'}>published</option>}
          </select>
        </label>

        <div className={'flex flex-col gap-1'}>
          <span className={LABEL}>Logic</span>
          {kind === 'filter' && (
            <PredicateEditor
              filterTerms={filterTerms.filter((t) => t !== term)}
              onChange={(next) => {
                setLogicValue(next);
                setPreview(null);
              }}
              value={logicValue as Predicate}
            />
          )}
          {kind === 'measure' && (
            <MeasureEditor
              onChange={(next) => {
                setLogicValue(next);
                setPreview(null);
              }}
              value={logicValue as Measure}
            />
          )}
          {kind === 'dimension' && (
            <DimensionEditor
              onChange={(next) => {
                setLogicValue(next);
                setPreview(null);
              }}
              value={logicValue as Dimension}
            />
          )}
        </div>

        {!isReadOnly && (
          <>
            <div className={'flex items-center gap-2'}>
              <Button disabled={isPreviewing} onClick={() => void runPreview()}>
                {isPreviewing ? 'Checking…' : 'Preview'}
              </Button>
              {preview?.kind === 'count' && (
                <p className={'text-xs text-ink-muted'}>
                  {preview.value === null
                    ? 'Shape is valid. No cohort to preview for this kind.'
                    : `${preview.value.toLocaleString()} ${preview.value === 1 ? 'patient' : 'patients'} would match.`}
                </p>
              )}
              {preview?.kind === 'error' && (
                <p className={'text-xs text-danger'}>{preview.message}</p>
              )}
            </div>

            <label className={'flex flex-col gap-1'}>
              <span className={LABEL}>Why this change</span>
              <input
                className={INPUT}
                onChange={(event) => {
                  setChangeReason(event.target.value);
                }}
                placeholder={'e.g. tightened after clinical review'}
                value={changeReason}
              />
            </label>

            {formError && <p className={'text-xs text-danger'}>{formError}</p>}

            <div className={'flex flex-wrap items-center gap-2 pt-1'}>
              <Button disabled={actions.isBusy} onClick={() => void save()} variant={'primary'}>
                {isNew ? 'Create draft' : 'Save'}
              </Button>
              {!isNew && definition.status === 'draft' && (
                <Button disabled={actions.isBusy} onClick={() => void publish()}>
                  Publish
                </Button>
              )}
              {!isNew && (
                <Button
                  danger={isConfirmingDelete}
                  disabled={actions.isBusy}
                  onClick={() => void remove()}
                >
                  {isConfirmingDelete ? 'Really delete?' : 'Delete'}
                </Button>
              )}
            </div>
          </>
        )}
      </fieldset>

      {!isNew && (
        <div className={'mt-2 border-t border-ink/5 pt-4'}>
          <h3 className={LABEL}>History</h3>
          {history.isPending && <p className={'mt-2 text-[11px] text-ink-muted'}>Loading…</p>}
          {history.error && (
            <div className={'mt-2'}>
              <InlineError
                message={`Could not load the history. ${errorMessage(history.error)}`}
                onRetry={() => void history.refetch()}
              />
            </div>
          )}
          <ul className={'mt-2 flex flex-col gap-2'}>
            {history.data?.map((entry) => (
              <li className={'text-[11px] text-ink-muted'} key={entry.id}>
                <span className={'font-medium text-ink'}>v{entry.version}</span> {entry.action} by{' '}
                {entry.changedBy}, {formatDateTime(entry.createdAt)} — {entry.changeReason}
              </li>
            ))}
            {history.data?.length === 0 && (
              <li className={'text-[11px] text-ink-muted'}>No history yet.</li>
            )}
          </ul>
        </div>
      )}
    </Page>
  );
}
