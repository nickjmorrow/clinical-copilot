import Button from 'src/components/Button';
import StringListInput from 'src/components/StringListInput';
import {
  COMPARISONS,
  emptyPredicate,
  EXPOSURES,
  type Predicate,
  PREDICATE_TYPES,
  VITAL_STATUSES,
} from 'src/predicates';
import { INPUT, LABEL } from 'src/styles';

interface Props {
  filterTerms: string[];
  onChange: (value: Predicate) => void;
  onRemove?: () => void;
  value: Predicate;
}

// `w-full` fights `flex-1` over the flex-basis calculation and can collapse
// an input to a few pixels wide — see the same constant in
// `AgeBandListInput.tsx`, where this was first found live.
const FLEX_INPUT = INPUT.replace('w-full ', '');

const TYPE_LABEL: Record<Predicate['type'], string> = {
  age_threshold: 'Age',
  all_of: 'All of (AND)',
  any_of: 'Any of (OR)',
  medication_attribute: 'On a tiered medication',
  not: 'Not',
  observation_threshold: 'Observation threshold',
  term: 'Another defined term',
  vital_status: 'Alive / deceased',
};

/**
 * One filter predicate, editable — and, for `all_of`/`any_of`/`not`,
 * recursive: a composed predicate renders one `PredicateEditor` per member,
 * each capable of being composed again. `app/clinical/predicates.py` caps
 * real nesting at 8 levels; nothing here enforces a matching limit, because
 * the backend's Preview/save validation is the actual gate and a client-side
 * cap would just be a second, possibly-wrong copy of the same rule.
 *
 * `onRemove` is present only when this editor is one member of a parent's
 * list (or the sole child of a `not`) — the top-level predicate for a
 * definition cannot remove itself, it can only change `type`.
 */
export default function PredicateEditor({ filterTerms, onChange, onRemove, value }: Props) {
  const setType = (type: Predicate['type']) => {
    onChange(emptyPredicate(type));
  };

  return (
    <div className={'flex flex-col gap-2 rounded-lg border border-ink/10 p-3'}>
      <div className={'flex items-center gap-2'}>
        <select
          className={[FLEX_INPUT, 'min-w-0 flex-1'].join(' ')}
          onChange={(event) => {
            setType(event.target.value as Predicate['type']);
          }}
          value={value.type}
        >
          {PREDICATE_TYPES.map((type) => (
            <option key={type} value={type}>
              {TYPE_LABEL[type]}
            </option>
          ))}
        </select>
        {onRemove && (
          <Button onClick={onRemove} size={'sm'}>
            Remove
          </Button>
        )}
      </div>

      {value.type === 'observation_threshold' && (
        <>
          <StringListInput
            label={'LOINC codes'}
            onChange={(codes) => {
              onChange({ ...value, codes });
            }}
            placeholder={'33914-3'}
            value={value.codes}
          />
          <StringListInput
            label={'Units — accepted, never converted'}
            onChange={(units) => {
              onChange({ ...value, units });
            }}
            placeholder={'mL/min/{1.73_m2}, mL/min'}
            value={value.units}
          />
          <div className={'flex items-end gap-2'}>
            <label className={'flex flex-1 flex-col gap-1'}>
              <span className={LABEL}>Operator</span>
              <select
                className={INPUT}
                onChange={(event) => {
                  onChange({ ...value, operator: event.target.value as typeof value.operator });
                }}
                value={value.operator}
              >
                {COMPARISONS.map((op) => (
                  <option key={op} value={op}>
                    {op}
                  </option>
                ))}
              </select>
            </label>
            <label className={'flex flex-1 flex-col gap-1'}>
              <span className={LABEL}>Value</span>
              <input
                className={INPUT}
                onChange={(event) => {
                  onChange({ ...value, value: Number(event.target.value) });
                }}
                type={'number'}
                value={value.value}
              />
            </label>
          </div>
          <label className={'flex items-center gap-2 text-xs text-ink'}>
            <input
              checked={value.most_recent}
              onChange={(event) => {
                onChange({ ...value, most_recent: event.target.checked });
              }}
              type={'checkbox'}
            />
            Most recent value only (uncheck for "ever recorded")
          </label>
        </>
      )}

      {value.type === 'medication_attribute' && (
        <>
          <label className={'flex flex-col gap-1'}>
            <span className={LABEL}>Attribute</span>
            <input
              className={INPUT}
              onChange={(event) => {
                onChange({ ...value, attribute: event.target.value });
              }}
              placeholder={'nephrotoxic_risk'}
              value={value.attribute}
            />
          </label>
          <StringListInput
            label={'Values'}
            onChange={(values) => {
              onChange({ ...value, in: values });
            }}
            placeholder={'high, moderate'}
            value={value.in}
          />
          <div className={'flex items-end gap-2'}>
            <label className={'flex flex-1 flex-col gap-1'}>
              <span className={LABEL}>Exposure</span>
              <select
                className={INPUT}
                onChange={(event) => {
                  const exposure = event.target.value as (typeof EXPOSURES)[number];
                  onChange({
                    ...value,
                    exposure,
                    within_days: exposure === 'recent' ? (value.within_days ?? 730) : null,
                  });
                }}
                value={value.exposure}
              >
                {EXPOSURES.map((exposure) => (
                  <option key={exposure} value={exposure}>
                    {exposure}
                  </option>
                ))}
              </select>
            </label>
            {value.exposure === 'recent' && (
              <label className={'flex flex-1 flex-col gap-1'}>
                <span className={LABEL}>Within days</span>
                <input
                  className={INPUT}
                  onChange={(event) => {
                    onChange({ ...value, within_days: Number(event.target.value) });
                  }}
                  type={'number'}
                  value={value.within_days ?? 0}
                />
              </label>
            )}
          </div>
        </>
      )}

      {value.type === 'age_threshold' && (
        <div className={'flex items-end gap-2'}>
          <label className={'flex flex-1 flex-col gap-1'}>
            <span className={LABEL}>Operator</span>
            <select
              className={INPUT}
              onChange={(event) => {
                onChange({ ...value, operator: event.target.value as typeof value.operator });
              }}
              value={value.operator}
            >
              {COMPARISONS.map((op) => (
                <option key={op} value={op}>
                  {op}
                </option>
              ))}
            </select>
          </label>
          <label className={'flex flex-1 flex-col gap-1'}>
            <span className={LABEL}>Age</span>
            <input
              className={INPUT}
              onChange={(event) => {
                onChange({ ...value, value: Number(event.target.value) });
              }}
              type={'number'}
              value={value.value}
            />
          </label>
        </div>
      )}

      {value.type === 'vital_status' && (
        <label className={'flex flex-col gap-1'}>
          <span className={LABEL}>Status</span>
          <select
            className={INPUT}
            onChange={(event) => {
              onChange({ ...value, status: event.target.value as typeof value.status });
            }}
            value={value.status}
          >
            {VITAL_STATUSES.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </label>
      )}

      {value.type === 'term' && (
        <label className={'flex flex-col gap-1'}>
          <span className={LABEL}>Term</span>
          {filterTerms.length > 0 ? (
            <select
              className={INPUT}
              onChange={(event) => {
                onChange({ ...value, term: event.target.value });
              }}
              value={value.term}
            >
              <option value={''}>choose a term…</option>
              {[...new Set([value.term, ...filterTerms].filter(Boolean))].map((term) => (
                <option key={term} value={term}>
                  {term}
                </option>
              ))}
            </select>
          ) : (
            <input
              className={INPUT}
              onChange={(event) => {
                onChange({ ...value, term: event.target.value });
              }}
              value={value.term}
            />
          )}
        </label>
      )}

      {(value.type === 'all_of' || value.type === 'any_of') && (
        <div className={'flex flex-col gap-2 border-l-2 border-ink/10 pl-3'}>
          {value.of.map((member, index) => (
            <PredicateEditor
              filterTerms={filterTerms}
              // No stable id per member; position in `of` is the identity a
              // reorder-free list of conditions actually has.
              key={index}
              onChange={(next) => {
                const of = [...value.of];
                of[index] = next;
                onChange({ ...value, of });
              }}
              onRemove={
                value.of.length > 2
                  ? () => {
                      onChange({ ...value, of: value.of.filter((_, i) => i !== index) });
                    }
                  : undefined
              }
              value={member}
            />
          ))}
          <Button
            onClick={() => {
              onChange({ ...value, of: [...value.of, emptyPredicate('age_threshold')] });
            }}
            size={'sm'}
          >
            + Add condition
          </Button>
        </div>
      )}

      {value.type === 'not' && (
        <div className={'border-l-2 border-ink/10 pl-3'}>
          <PredicateEditor
            filterTerms={filterTerms}
            onChange={(next) => {
              onChange({ ...value, of: next });
            }}
            value={value.of}
          />
        </div>
      )}
    </div>
  );
}
