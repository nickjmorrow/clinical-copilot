import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { browsePatients } from 'src/api/browse';
import { isForbidden } from 'src/api/client';
import Button from 'src/components/Button';
import CuratorsOnly from 'src/components/CuratorsOnly';
import EmptyState from 'src/components/EmptyState';
import LoadFailed from 'src/components/LoadFailed';
import RowTable from 'src/components/RowTable';
import { formatDate } from 'src/format';

const PAGE_SIZE = 50;

/**
 * The raw patient table, paged — SEMANTIC_LAYER.md § 3: "the fastest way to
 * lose faith in an answer is to be unable to look at the rows behind it."
 * No question, no filter, no definitions resolved — just the dataset
 * itself, through the same column allowlist and row-level scope every other
 * path uses. Gated `RequireReviewer` on the backend; a curator or auditor
 * paging through this is not a chat question.
 */
export default function PatientBrowser() {
  const [offset, setOffset] = useState(0);

  const page = useQuery({
    queryFn: () => browsePatients({ limit: PAGE_SIZE, offset }),
    queryKey: ['browse', 'patients', offset],
  });

  if (isForbidden(page.error)) return <CuratorsOnly />;
  if (page.error) {
    return (
      <LoadFailed
        error={page.error}
        onRetry={() => void page.refetch()}
        title={'Could not load the patient table.'}
      />
    );
  }

  if (page.data?.outcome === 'rejected') {
    return <EmptyState detail={page.data.reason ?? undefined} title={'Refused.'} />;
  }

  const total = page.data?.total ?? 0;
  const hasPrevious = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;

  return (
    <div className={'flex h-full flex-col overflow-y-auto px-6 py-5'}>
      <div className={'mx-auto flex w-full max-w-4xl flex-col gap-3'}>
        <div>
          <h2 className={'text-sm font-semibold tracking-tight text-ink'}>Patients</h2>
          <p className={'mt-1 text-xs text-ink-muted'}>
            The patient table as stored, within your access scope — no question asked, no definition
            applied.
          </p>
        </div>
        {page.data && (
          <>
            <RowTable columns={page.data.columns} rows={page.data.rows} />

            <div className={'flex items-center justify-between text-xs text-ink-muted'}>
              <p>
                {total === 0
                  ? 'No patients in scope.'
                  : `${String(offset + 1)}–${String(Math.min(offset + PAGE_SIZE, total))} of ${String(total)}`}
              </p>
              <div className={'flex gap-2'}>
                <Button
                  disabled={!hasPrevious}
                  onClick={() => {
                    setOffset((current) => Math.max(0, current - PAGE_SIZE));
                  }}
                  size={'sm'}
                >
                  Previous
                </Button>
                <Button
                  disabled={!hasNext}
                  onClick={() => {
                    setOffset((current) => current + PAGE_SIZE);
                  }}
                  size={'sm'}
                >
                  Next
                </Button>
              </div>
            </div>

            {page.data.dataset && (
              <p className={'text-[11px] text-ink-muted'}>
                {page.data.dataset.source}, as of {formatDate(page.data.dataset.asOfDate)}.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
