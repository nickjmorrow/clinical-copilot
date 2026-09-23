import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router';
import { errorMessage, isForbidden } from 'src/api/client';
import { checkModel, type Definition, definitionKeys, listDefinitions } from 'src/api/definitions';
import InlineError from 'src/components/InlineError';
import NewItemLink from 'src/components/NewItemLink';
import { paths } from 'src/paths';
import { SIDEBAR_HEADING } from 'src/styles';

const GROUPS: { kind: Definition['kind']; label: string }[] = [
  { kind: 'filter', label: 'Filters' },
  { kind: 'measure', label: 'Measures' },
  { kind: 'dimension', label: 'Group by' },
];

const STATUS_LABEL: Record<Definition['status'], string> = {
  deprecated: 'Deprecated',
  draft: 'Draft',
  published: 'Published',
};

/**
 * The sidebar's list in Definitions: every definition, any status, grouped
 * by kind. A term with a `check_model()` warning — `hyperkalemia` matching
 * nobody, today — carries a marker here rather than needing its own page to
 * discover.
 *
 * Fetches the list and the model check itself; `DefinitionsEditor` beside it
 * shares the list's query key, so the two cost one request. Rows are links,
 * and the highlight follows the address.
 */
export default function DefinitionList() {
  // `new`, an id, or null for nothing chosen — straight from the address.
  const { selection = null } = useParams();
  const definitions = useQuery({ queryFn: listDefinitions, queryKey: definitionKeys.all });
  const warnings = useQuery({ queryFn: checkModel, queryKey: definitionKeys.modelCheck });

  // Nothing to list for someone without the role; the page beside this says why.
  if (isForbidden(definitions.error)) return null;

  const warnedTerms = new Set((warnings.data ?? []).map((warning) => warning.term));

  return (
    <>
      <div className={'p-2'}>
        <NewItemLink
          isActive={selection === 'new'}
          label={'+ New definition'}
          to={paths.definitions('new')}
        />
      </div>

      {definitions.error ? (
        <div className={'px-2'}>
          <InlineError
            message={`Could not load the definitions. ${errorMessage(definitions.error)}`}
            onRetry={() => void definitions.refetch()}
          />
        </div>
      ) : (
        <div className={'min-h-0 flex-1 overflow-y-auto px-2 pb-2'}>
          {GROUPS.map(({ kind, label }) => {
            const inGroup = (definitions.data ?? []).filter(
              (definition) => definition.kind === kind,
            );
            if (inGroup.length === 0) return null;

            return (
              <div key={kind}>
                <h3 className={SIDEBAR_HEADING}>{label}</h3>
                <ul className={'flex flex-col'}>
                  {inGroup.map((definition) => (
                    <li key={definition.id}>
                      <Link
                        aria-current={definition.id === selection ? 'page' : undefined}
                        className={[
                          'flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs transition',
                          definition.id === selection
                            ? 'bg-accent/10 font-medium text-ink'
                            : 'text-ink-muted hover:bg-ink/5 hover:text-ink',
                        ].join(' ')}
                        to={paths.definitions(definition.id)}
                      >
                        <span className={'min-w-0 flex-1 truncate'}>{definition.term}</span>
                        {warnedTerms.has(definition.term) && (
                          <span
                            aria-label={'Flagged by the model check'}
                            title={'Flagged by the model check'}
                          >
                            ⚠
                          </span>
                        )}
                        {definition.status !== 'published' && (
                          <span className={'shrink-0 text-[10px] text-ink-muted/80'}>
                            {STATUS_LABEL[definition.status]}
                          </span>
                        )}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
