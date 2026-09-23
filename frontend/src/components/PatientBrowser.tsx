import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { browsePatients } from 'src/api/browse';
import { isForbidden } from 'src/api/client';
import Button from 'src/components/Button';
import CuratorsOnly from 'src/components/CuratorsOnly';
import EmptyState from 'src/components/EmptyState';
import LoadFailed from 'src/components/LoadFailed';
import Loading from 'src/components/Loading';
import Page from 'src/components/Page';
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
    // The page on screen stays while the next one loads, rather than the
    // table — and the Previous/Next buttons under it — blanking on every click.
    placeholderData: keepPreviousData,
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

  if (page.isPending) return <Loading />;

  if (page.data.outcome === 'rejected') {
    return (
      <EmptyState
        detail={page.data.reason ?? undefined}
        title={'The patient table refused this request.'}
      />
    );
  }

  const total = page.data.total;
  const hasPrevious = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;

  return (
    <Page
      description={
        'The patient table as stored, within your access scope — no question asked, no definition applied.'
      }
      title={'Patients'}
      width={'table'}
    >
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
    </Page>
  );
}
