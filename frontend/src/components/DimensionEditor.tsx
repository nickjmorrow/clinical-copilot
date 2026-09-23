import AgeBandListInput from 'src/components/AgeBandListInput';
import {
  type Dimension,
  DIMENSION_TYPES,
  emptyDimension,
  EXPOSURES,
  PATIENT_COLUMNS,
} from 'src/predicates';
import { INPUT, LABEL } from 'src/styles';

interface Props {
  onChange: (value: Dimension) => void;
  value: Dimension;
}

const TYPE_LABEL: Record<Dimension['type'], string> = {
  age_band: 'Age band',
  medication_group: 'Medication tier',
  patient_column: 'Patient column',
};

/**
 * One dimension — what a measure gets grouped by. `medication_group` is the
 * one that fans out (a patient in two tiers is counted in both), which is
 * why `app/clinical/assembler.py` refuses to combine it with any measure but
 * a patient count — a refusal this editor cannot see happen until Preview or
 * Save, since that check lives with the assembler, not the shape.
 */
export default function DimensionEditor({ onChange, value }: Props) {
  return (
    <div className={'flex flex-col gap-2 rounded-lg border border-ink/10 p-3'}>
      <select
        className={INPUT}
        onChange={(event) => {
          onChange(emptyDimension(event.target.value as Dimension['type']));
        }}
        value={value.type}
      >
        {DIMENSION_TYPES.map((type) => (
          <option key={type} value={type}>
            {TYPE_LABEL[type]}
          </option>
        ))}
      </select>

      {value.type === 'patient_column' && (
        <label className={'flex flex-col gap-1'}>
          <span className={LABEL}>Column</span>
          <select
            className={INPUT}
            onChange={(event) => {
              onChange({ ...value, column: event.target.value as typeof value.column });
            }}
            value={value.column}
          >
            {PATIENT_COLUMNS.map((column) => (
              <option key={column} value={column}>
                {column}
              </option>
            ))}
          </select>
        </label>
      )}

      {value.type === 'age_band' && (
        <AgeBandListInput
          bands={value.bands}
          onChange={(bands) => {
            onChange({ ...value, bands });
          }}
        />
      )}

      {value.type === 'medication_group' && (
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
    </div>
  );
}
