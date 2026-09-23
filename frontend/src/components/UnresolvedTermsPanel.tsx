import { useQuery } from '@tanstack/react-query';
import { auditKeys, listUnresolvedTerms } from 'src/api/audit';
import { isForbidden } from 'src/api/client';
import CuratorsOnly from 'src/components/CuratorsOnly';
import EmptyState from 'src/components/EmptyState';
import LoadFailed from 'src/components/LoadFailed';
import Loading from 'src/components/Loading';
import Page from 'src/components/Page';
import { formatDateTime } from 'src/format';

/**
 * The backlog for what to define next — SEMANTIC_LAYER.md § 14. Every
 * question the system had to ask a clarification for, grouped by the raw
 * question and ranked by how often it has come up: the most-asked missing
 * term is the one worth writing a definition for first.
 *
 * Read-only, and deliberately not editable from here — the fix for an
 * unresolved question is a new or renamed definition, and that already has
 * its own surface in Definitions.
 */
export default function UnresolvedTermsPanel() {
  const terms = useQuery({
    queryFn: listUnresolvedTerms,
    queryKey: auditKeys.unresolvedTerms,
  });

  if (isForbidden(terms.error)) return <CuratorsOnly />;
  if (terms.error) {
    return (
      <LoadFailed
        error={terms.error}
        onRetry={() => void terms.refetch()}
        title={'Could not load the unresolved-term report.'}
      />
    );
  }
  if (terms.isPending) return <Loading />;

  if (terms.data.length === 0) {
    return (
      <EmptyState
        detail={'Every question asked so far has resolved to a defined term.'}
        title={'Nothing unresolved.'}
      />
    );
  }

  return (
    <Page
      description={
        'Questions that stopped for a clarification because a term had no definition, most-asked first. The top of this list is what to define next.'
      }
      title={'Unresolved terms'}
    >
      {/* Scrolls sideways on its own rather than taking the page with it. */}
      <div className={'overflow-x-auto'}>
        <table className={'w-full border-collapse text-xs'}>
          <thead>
            <tr className={'border-b border-ink/10 text-left text-ink-muted'}>
              <th className={'py-2 pr-4 font-medium'}>Question</th>
              <th className={'py-2 pr-4 font-medium'}>Asked</th>
              <th className={'py-2 pr-4 font-medium'}>Last asked</th>
              <th className={'py-2 font-medium'}>By</th>
            </tr>
          </thead>
          <tbody>
            {terms.data.map((entry) => (
              <tr className={'border-b border-ink/5'} key={entry.rawQuestion}>
                <td className={'py-2 pr-4 text-ink'}>{entry.rawQuestion}</td>
                <td className={'py-2 pr-4 text-ink-muted tabular-nums'}>{entry.count}×</td>
                <td className={'py-2 pr-4 text-ink-muted'}>{formatDateTime(entry.lastAsked)}</td>
                <td className={'py-2 text-ink-muted'}>{entry.askedBy.join(', ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Page>
  );
}
