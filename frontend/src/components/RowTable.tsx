interface Props {
  columns: string[];
  rows: Record<string, unknown>[];
}

function cell(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'number') return value.toLocaleString();
  if (typeof value === 'string' || typeof value === 'boolean') return String(value);
  // A row's keys are term names, not a fixed schema, so this is a real
  // possibility rather than defensive dead code — a future dimension or
  // measure could resolve to something structured, and this is what stops
  // that rendering as the literal text "[object Object]".
  return JSON.stringify(value);
}

/**
 * A cohort or aggregate answer's rows, as a table. Shared by
 * `SavedQuestionResult` and the "view full roster" drilldown on a chat
 * answer's `ToolCard` — the second caller that made this worth pulling out
 * of the first one, rather than a table built twice.
 */
export default function RowTable({ columns, rows }: Props) {
  if (rows.length === 0) return null;

  return (
    <div className={'overflow-x-auto rounded-lg border border-ink/10'}>
      <table className={'w-full text-xs'}>
        <thead>
          <tr className={'border-b border-ink/10 bg-surface-raised'}>
            {columns.map((column) => (
              <th className={'px-2.5 py-1.5 text-left font-medium text-ink-muted'} key={column}>
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            // Rows carry no id of their own — a cohort row's `patientId` is
            // unique but an aggregate row's group is not, so the whole row,
            // joined, is the one value guaranteed to tell two rows apart.
            const rowKey = columns.map((column) => cell(row[column])).join('|');
            return (
              <tr className={'border-b border-ink/5 last:border-0'} key={rowKey}>
                {columns.map((column) => (
                  <td className={'px-2.5 py-1.5 text-ink'} key={column}>
                    {cell(row[column])}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
