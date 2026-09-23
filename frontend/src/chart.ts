/**
 * The aggregate result of a `find_patients` call (or a saved question's run)
 * — `{columns, rows, measures, groupBy}`, built by `_answer_data` in
 * `backend/app/tools/find_patients.py` — folded into something a bar chart
 * can draw. Pure, no React, for the same reason `turns.ts` sits out here.
 *
 * SEMANTIC_LAYER.md § 4's rule: **the chart is derived from the result, not
 * authored by the model.** The model named a measure and a dimension; this is
 * the one place that decides what a bar means, and it is the same fold for
 * every caller — `ToolCard` mid-answer and `SavedQuestionResult` after a run
 * both call this rather than each shaping the rows their own way.
 *
 * `data` arrives as untyped JSON off the wire (a tool result's structured
 * half has no fixed shape — its keys are whichever terms the question named),
 * so every read here is defensive. A malformed or unexpected shape returns
 * `null`, the same as "nothing to plot", rather than throwing — a chart that
 * cannot be drawn is not a reason to break the transcript.
 */

export interface ChartPoint {
  label: string;
  value: number;
}

export interface ChartSeries {
  measure: string;
  points: ChartPoint[];
}

export interface ChartData {
  series: ChartSeries[];
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function isRecordArray(value: unknown): value is Record<string, unknown>[] {
  return (
    Array.isArray(value) &&
    value.every((item) => typeof item === 'object' && item !== null && !Array.isArray(item))
  );
}

function toNumber(value: unknown): null | number {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/** One row's category label. Joins every group-by dimension's value with
 *  `·` — the assembler groups by at most a couple of dimensions in practice,
 *  and a single joined label is a category axis a bar chart already knows how
 *  to draw, rather than a grid this shape does not need yet. Falls back to a
 *  1-based ordinal for an ungrouped aggregate (a single measure with no
 *  `groupBy` at all — one bar, not zero). */
function labelFor(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return JSON.stringify(value);
}

function categoryLabel(row: Record<string, unknown>, groupBy: string[], index: number): string {
  if (groupBy.length === 0) return `#${String(index + 1)}`;
  return groupBy.map((dimension) => labelFor(row[dimension])).join(' · ');
}

export function toChartData(data: unknown): ChartData | null {
  if (typeof data !== 'object' || data === null) return null;
  const record = data as Record<string, unknown>;

  const rows = record.rows;
  const measures = record.measures;
  const groupBy = record.groupBy;
  if (!isRecordArray(rows) || !isStringArray(measures) || !isStringArray(groupBy)) return null;
  if (rows.length === 0 || measures.length === 0) return null;

  const series: ChartSeries[] = measures.map((measure) => ({
    measure,
    points: rows.map((row, index) => ({
      label: categoryLabel(row, groupBy, index),
      value: toNumber(row[measure]) ?? 0,
    })),
  }));

  return { series };
}
