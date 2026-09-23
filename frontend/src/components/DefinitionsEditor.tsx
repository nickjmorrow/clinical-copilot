import { useQuery } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router';
import { isForbidden } from 'src/api/client';
import { definitionKeys, listDefinitions } from 'src/api/definitions';
import CuratorsOnly from 'src/components/CuratorsOnly';
import DefinitionForm from 'src/components/DefinitionForm';
import DefinitionList from 'src/components/DefinitionList';
import EmptyState from 'src/components/EmptyState';
import LoadFailed from 'src/components/LoadFailed';
import Loading from 'src/components/Loading';
import PickFromList from 'src/components/PickFromList';
import useRoles from 'src/hooks/useRoles';
import { paths } from 'src/paths';

/**
 * The definitions editor: one definition's form, beside the list in the
 * sidebar (`DefinitionList`). A real editing surface — a dozen fields, a
 * recursive predicate builder, history — which is why it takes the whole page
 * rather than a side panel.
 *
 * `DefinitionForm` seeds its state from the definition once, when it mounts,
 * so it must not mount before there is a definition to seed it from: on a
 * refresh at `/definitions/<id>`, rendering it while the list is still
 * loading would show an empty *create* form that stayed empty after the data
 * arrived. So an id waits for the list, and one the list does not contain is
 * said so rather than quietly treated as "new".
 *
 * Keyed by the selection so switching definitions remounts the form instead
 * of an effect syncing props into state — see CONVENTIONS.md > Frontend.
 *
 * Anyone may read a definition; only a curator gets a form that writes. The
 * server enforces that either way — this decides what is worth showing.
 */
export default function DefinitionsEditor() {
  // `new`, an id, or null for nothing chosen — straight from the address.
  const { selection = null } = useParams();
  const navigate = useNavigate();
  const definitions = useQuery({ queryFn: listDefinitions, queryKey: definitionKeys.all });
  const { canCurate, isKnown } = useRoles();

  if (isForbidden(definitions.error)) return <CuratorsOnly />;

  if (selection === null) {
    return (
      <PickFromList list={<DefinitionList />}>
        {canCurate ? (
          <EmptyState
            detail={
              'Every change here is versioned — see the history at the bottom of a definition once you have made one.'
            }
            title={'Pick a definition to edit, or start a new one.'}
          />
        ) : (
          <EmptyState
            detail={
              "Each is the hospital's own answer to what a term means: the exact logic a question is answered with, the reasoning behind it, and every past version."
            }
            title={'Pick a definition to see what it means.'}
          />
        )}
      </PickFromList>
    );
  }

  // Creating is a curator's. Wait for the roles rather than flash the notice.
  if (selection === 'new' && !canCurate) return isKnown ? <CuratorsOnly /> : null;

  if (definitions.isPending) return <Loading />;
  if (definitions.error) {
    return (
      <LoadFailed
        error={definitions.error}
        onRetry={() => void definitions.refetch()}
        title={'Could not load the definitions.'}
      />
    );
  }

  const selected =
    selection === 'new' ? null : definitions.data.find((definition) => definition.id === selection);
  if (selected === undefined) {
    return (
      <EmptyState
        detail={'It may have been deleted. Pick another from the list.'}
        title={'That definition is not available.'}
      />
    );
  }

  // For `PredicateEditor`'s "another defined term" field: only a filter can
  // be referenced by `{"type": "term", ...}` — `definition_service.
  // load_vocabulary` refuses a reference to a measure or a dimension.
  const filterTerms = definitions.data
    .filter((definition) => definition.kind === 'filter')
    .map((definition) => definition.term);

  return (
    <DefinitionForm
      definition={selected}
      filterTerms={filterTerms}
      isReadOnly={!canCurate}
      key={selection}
      onDeleted={() => {
        void navigate(paths.definitions());
      }}
      onSaved={(id) => {
        // Saving a new definition is the form gaining an address, not a move
        // somewhere else — so it replaces, and Back does not reopen it empty.
        // Saving an existing one is already at its address; navigating there
        // again would only stack a duplicate entry for Back to stall on.
        if (selection === 'new') void navigate(paths.definitions(id), { replace: true });
      }}
    />
  );
}
