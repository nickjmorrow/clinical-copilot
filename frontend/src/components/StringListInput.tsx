import { useState } from 'react';
import { INPUT, LABEL } from 'src/styles';

const parse = (text: string) =>
  text
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);

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
 * plain input is the simplest thing that works, in a codebase with no other
 * tag-editing UI to share one with.
 */
export default function StringListInput({ label, onChange, placeholder, value }: Props) {
  // What was typed, kept as typed. Rebuilding the text from `value` on every
  // keystroke threw away a trailing comma the instant it was typed, so a
  // second value could only ever be pasted. The typed text is shown while it
  // still means `value`; if `value` changes from outside, the new list wins.
  const [text, setText] = useState(value.join(', '));
  const shown = JSON.stringify(parse(text)) === JSON.stringify(value) ? text : value.join(', ');

  return (
    <label className={'flex flex-col gap-1'}>
      <span className={LABEL}>{label}</span>
      <input
        className={INPUT}
        onChange={(event) => {
          setText(event.target.value);
          onChange(parse(event.target.value));
        }}
        placeholder={placeholder}
        value={shown}
      />
    </label>
  );
}
