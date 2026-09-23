import type { ChartData } from 'src/chart';

interface Props {
  data: ChartData;
}

const BAR_HEIGHT = 20;
const GAP = 8;
const LABEL_WIDTH = 96;
const BAR_TRACK_WIDTH = 200;
const VALUE_GUTTER = 52;

/**
 * A horizontal bar chart, one section per measure. SEMANTIC_LAYER.md § 4's
 * rule in code: this draws whatever `toChartData` handed it and decides
 * nothing about the data — no binning, no scale choice beyond "longest bar
 * fills the track" — because a presentational judgement a reader cannot
 * review is the same failure as a model writing SQL, one layer up.
 *
 * Horizontal rather than vertical bars because the category labels here are
 * text (an age band, a state, a drug tier) rather than short numbers, and
 * text reads left-to-right beside its bar instead of rotated under one.
 *
 * Plain SVG, not a charting library: the shape this draws — one series, a
 * handful of categories — does not need one, and this codebase already
 * reaches for the smallest thing that works before reaching for a dependency.
 */
export default function Chart({ data }: Props) {
  return (
    <div className={'flex flex-col gap-4'}>
      {data.series.map((series) => {
        const max = Math.max(0, ...series.points.map((point) => point.value)) || 1;
        const height = series.points.length * (BAR_HEIGHT + GAP);
        const width = LABEL_WIDTH + BAR_TRACK_WIDTH + VALUE_GUTTER;

        return (
          <div key={series.measure}>
            <p className={'mb-1 text-[11px] font-medium text-ink-muted'}>{series.measure}</p>
            <svg
              aria-label={`${series.measure}, by category`}
              className={'w-full max-w-md'}
              role={'img'}
              viewBox={`0 0 ${String(width)} ${String(height)}`}
            >
              {series.points.map((point, index) => {
                const barWidth = Math.max((point.value / max) * BAR_TRACK_WIDTH, 1);
                const y = index * (BAR_HEIGHT + GAP);

                return (
                  <g key={`${point.label}-${String(index)}`}>
                    <text
                      className={'fill-ink-muted text-[10px]'}
                      dominantBaseline={'middle'}
                      textAnchor={'end'}
                      x={LABEL_WIDTH - 6}
                      y={y + BAR_HEIGHT / 2}
                    >
                      {point.label}
                    </text>
                    <rect
                      className={'fill-accent/70'}
                      height={BAR_HEIGHT}
                      rx={3}
                      width={barWidth}
                      x={LABEL_WIDTH}
                      y={y}
                    />
                    <text
                      className={'fill-ink text-[10px] tabular-nums'}
                      dominantBaseline={'middle'}
                      x={LABEL_WIDTH + barWidth + 6}
                      y={y + BAR_HEIGHT / 2}
                    >
                      {point.value.toLocaleString()}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>
        );
      })}
    </div>
  );
}
