import { INPUT, LABEL } from 'src/styles';

interface Props {
  label: string;
  onChange: (value: string[]) => void;
  placeholder?: string;
  value: string[];
}

/**
 * A `string[]` field — LOINC codes, units, curated-tier values — edited as
 * one comma-separated line, the same convention `DefinitionForm` already
 * uses for synonyms. A chip-per-value widget would look more finished; a
 * plain input is what a codebase with no other tag-editing UI anywhere
 * should reach for first, per CONVENTIONS.md's "three similar lines is better
 * than a premature abstraction."
 */
export default function StringListInput({ label, onChange, placeholder, value }: Props) {
  return (
    <label className={'flex flex-col gap-1'}>
      <span className={LABEL}>{label}</span>
      <input
        className={INPUT}
        onChange={(event) => {
          onChange(
            event.target.value
              .split(',')
              .map((item) => item.trim())
              .filter(Boolean),
          );
        }}
        placeholder={placeholder}
        value={value.join(', ')}
      />
    </label>
  );
}
