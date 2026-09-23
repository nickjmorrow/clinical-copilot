import { useQuery } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router';
import { isForbidden } from 'src/api/client';
import { definitionKeys, listDefinitions } from 'src/api/definitions';
import CuratorsOnly from 'src/components/CuratorsOnly';
import DefinitionForm from 'src/components/DefinitionForm';
import DefinitionList from 'src/components/DefinitionList';
import EmptyState from 'src/components/EmptyState';
import PickFromList from 'src/components/PickFromList';
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
 */
export default function DefinitionsEditor() {
  // `new`, an id, or null for nothing chosen — straight from the address.
  const { selection = null } = useParams();
  const navigate = useNavigate();
  const definitions = useQuery({ queryFn: listDefinitions, queryKey: definitionKeys.all });

  if (isForbidden(definitions.error)) return <CuratorsOnly />;

  if (selection === null) {
    return (
      <PickFromList list={<DefinitionList />}>
        <EmptyState
          detail={
            'Every change here is versioned — see the history at the bottom of a definition once you have made one.'
          }
          title={'Pick a definition to edit, or start a new one.'}
        />
      </PickFromList>
    );
  }

  if (definitions.isPending) return null;
  if (definitions.error) return <EmptyState title={'Could not load the definitions.'} />;

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
