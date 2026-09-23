import StringListInput from 'src/components/StringListInput';
import { AGGREGATES, emptyMeasure, type Measure, MEASURE_TYPES } from 'src/predicates';
import { INPUT, LABEL } from 'src/styles';

interface Props {
  onChange: (value: Measure) => void;
  value: Measure;
}

const TYPE_LABEL: Record<Measure['type'], string> = {
  observation_aggregate: 'Aggregate of an observation',
  patient_count: 'Patient count',
};

/** One measure — `patient_count` needs nothing further; `observation_aggregate`
 * needs the same code/unit declaration `PredicateEditor` uses for a threshold,
 * because it reads the same per-patient latest value. */
export default function MeasureEditor({ onChange, value }: Props) {
  return (
    <div className={'flex flex-col gap-2 rounded-lg border border-ink/10 p-3'}>
      <select
        className={INPUT}
        onChange={(event) => {
          onChange(emptyMeasure(event.target.value as Measure['type']));
        }}
        value={value.type}
      >
        {MEASURE_TYPES.map((type) => (
          <option key={type} value={type}>
            {TYPE_LABEL[type]}
          </option>
        ))}
      </select>

      {value.type === 'observation_aggregate' && (
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
          <label className={'flex flex-col gap-1'}>
            <span className={LABEL}>Aggregate</span>
            <select
              className={INPUT}
              onChange={(event) => {
                onChange({ ...value, aggregate: event.target.value as typeof value.aggregate });
              }}
              value={value.aggregate}
            >
              {AGGREGATES.map((aggregate) => (
                <option key={aggregate} value={aggregate}>
                  {aggregate}
                </option>
              ))}
            </select>
          </label>
        </>
      )}

      {value.type === 'patient_count' && (
        <p className={'text-xs text-ink-muted'}>
          Counts distinct patients matching the filters. No further fields.
        </p>
      )}
    </div>
  );
}
