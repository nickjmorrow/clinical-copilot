import Button from 'src/components/Button';
import { INPUT, LABEL } from 'src/styles';

interface Band {
  label: string;
  upto: null | number;
}

interface Props {
  bands: Band[];
  onChange: (bands: Band[]) => void;
}

// `w-full` and `flex-1`/an explicit width on the same element fight over the
// flex-basis calculation and can collapse to a sliver a few pixels wide — a
// real bug found live, not a style nit. `FLEX_INPUT` is `INPUT` with `w-full`
// stripped, for the two inputs in this row that size themselves from their
// flex context instead.
const FLEX_INPUT = INPUT.replace('w-full ', '');

/**
 * The ordered band list for an `age_band` dimension.
 *
 * The last band is always open-ended — `upto: null` — matching
 * `app/clinical/predicates.py`'s `_require_bands`: only the final entry may
 * omit it, and it must. So its `upto` field here is never editable, and
 * adding a band always inserts before it rather than after.
 */
export default function AgeBandListInput({ bands, onChange }: Props) {
  const update = (index: number, patch: Partial<Band>) => {
    onChange(bands.map((band, i) => (i === index ? { ...band, ...patch } : band)));
  };

  const remove = (index: number) => {
    if (bands.length <= 2) return;
    onChange(bands.filter((_, i) => i !== index));
  };

  const add = () => {
    // The last band is always open-ended, so a new one is inserted just
    // before it, ten years past whatever the last *finite* boundary was.
    const lastFinite = bands.at(-2);
    const upto = (lastFinite?.upto ?? 0) + 10;
    const openEnded = bands.at(-1);
    if (!openEnded) return;
    onChange([
      ...bands.slice(0, -1),
      { label: `${String(upto - 10)}-${String(upto)}`, upto },
      openEnded,
    ]);
  };

  return (
    <div className={'flex flex-col gap-1'}>
      <span className={LABEL}>Bands, youngest first</span>
      <div className={'flex flex-col gap-1.5'}>
        {bands.map((band, index) => {
          const isLast = index === bands.length - 1;
          return (
            // Age bands have no stable id of their own — index is the
            // position in the ordered list, which is the thing being edited.
            <div className={'flex items-center gap-1.5'} key={index}>
              <input
                className={[FLEX_INPUT, 'min-w-0 flex-1'].join(' ')}
                onChange={(event) => {
                  update(index, { label: event.target.value });
                }}
                placeholder={'label'}
                value={band.label}
              />
              <span className={'text-[11px] text-ink-muted'}>up to</span>
              <input
                className={[FLEX_INPUT, 'w-16 shrink-0'].join(' ')}
                disabled={isLast}
                onChange={(event) => {
                  const parsed = Number(event.target.value);
                  update(index, { upto: Number.isFinite(parsed) ? parsed : null });
                }}
                placeholder={isLast ? 'open' : ''}
                type={'number'}
                value={band.upto ?? ''}
              />
              <Button
                disabled={bands.length <= 2}
                onClick={() => {
                  remove(index);
                }}
                size={'sm'}
              >
                ×
              </Button>
            </div>
          );
        })}
      </div>
      <Button onClick={add} size={'sm'}>
        + Add band
      </Button>
    </div>
  );
}
