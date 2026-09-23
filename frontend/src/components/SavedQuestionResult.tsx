import type { SavedQuestionRun } from 'src/api/savedQuestions';
import { toChartData } from 'src/chart';
import Chart from 'src/components/Chart';
import RowTable from 'src/components/RowTable';
import { formatDate } from 'src/format';

interface Props {
  result: SavedQuestionRun;
}

/**
 * One run of a saved question — the same information `find_patients`' text
 * rendering carries (the definitions applied, the row count, unmeasured
 * patients), as a table rather than prose, because this panel is a UI
 * surface rather than something a model has to read.
 *
 * An aggregate result draws through `toChartData` — the same fold `ToolCard`
 * uses for a chat answer — above the table, so this panel gets both the
 * glance and the exact numbers a chart alone cannot give.
 */
export default function SavedQuestionResult({ result }: Props) {
  if (result.outcome !== 'answered') {
    return (
      <div className={'rounded-lg border border-ink/10 bg-surface-raised p-3 text-xs'}>
        <p className={'font-medium text-ink'}>
          {result.outcome === 'rejected' ? 'Refused.' : 'Could not resolve.'}
        </p>
        <p className={'mt-1 text-ink-muted'}>
          {result.reason ??
            `Unrecognised: ${result.unresolved.join(', ')} — the underlying definition may have changed since this was saved.`}
        </p>
      </div>
    );
  }

  const chart = result.aggregate
    ? toChartData({
        columns: result.columns,
        groupBy: result.resolvedDimensions.map((dimension) => dimension.term),
        measures: result.resolvedMeasures.map((measure) => measure.term),
        rows: result.rows,
      })
    : null;

  return (
    <div className={'flex flex-col gap-3'}>
      <div className={'flex flex-col gap-1 text-[11px] text-ink-muted'}>
        {[...result.resolvedTerms, ...result.resolvedMeasures, ...result.resolvedDimensions].map(
          (resolved) => (
            <p key={resolved.term}>
              <span className={'font-medium text-ink'}>{resolved.term}</span>:{' '}
              {resolved.description}
            </p>
          ),
        )}
      </div>

      <p className={'text-xs text-ink-muted'}>
        {result.aggregate
          ? `${result.rowCount} group(s).`
          : `${result.rowCount} matching patient(s).`}
        {result.truncated && ' This is a capped page, not the whole result.'}
      </p>

      {result.unmeasured.map((entry) => (
        <p className={'text-[11px] text-ink-muted'} key={entry.term}>
          {entry.count} patient(s) could not be evaluated for &ldquo;{entry.term}&rdquo; — excluded,
          not counted as not meeting it.
        </p>
      ))}

      {chart && <Chart data={chart} />}

      <RowTable columns={result.columns} rows={result.rows} />

      {result.dataset && (
        <p className={'text-[11px] text-ink-muted'}>
          {result.dataset.source}, as of {formatDate(result.dataset.asOfDate)}.
        </p>
      )}
    </div>
  );
}
