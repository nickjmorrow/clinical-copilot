import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useCallback } from 'react';
import {
  createDefinition,
  type Definition,
  type DefinitionDraft,
  definitionKeys,
  type DefinitionPatch,
  deleteDefinition,
  publishDefinition,
  updateDefinition,
} from 'src/api/definitions';

export interface DefinitionActions {
  isBusy: boolean;
  create: (draft: DefinitionDraft) => Promise<Definition>;
  update: (id: string, patch: DefinitionPatch) => Promise<Definition>;
  publish: (id: string, changeReason: string) => Promise<Definition>;
  remove: (id: string, changeReason: string) => Promise<void>;
}

/**
 * The four things you can do to a definition, plus the invalidation each one
 * needs. Not `preview` — that has no effect on anything cached, so the form
 * owns it directly, the way it owns the count it gets back.
 *
 * Every mutation invalidates the same four query keys: the list (a term
 * changed), the one detail (if it was open), its history (a new row just
 * landed), and the model check (an edit can turn a warning on or off — the
 * `hyperkalemia` case is exactly this: matching nobody is a fact about the
 * dataset a threshold edit can change).
 */
export default function useDefinitionActions(): DefinitionActions {
  const queryClient = useQueryClient();

  const invalidate = useCallback(
    (id?: string) => {
      void queryClient.invalidateQueries({ queryKey: definitionKeys.modelCheck });
      if (id) {
        void queryClient.invalidateQueries({ queryKey: definitionKeys.detail(id) });
        void queryClient.invalidateQueries({ queryKey: definitionKeys.history(id) });
      }
      // Returned, so the mutation waits for it: every caller navigates next,
      // and the page it lands on looks the definition up in this list. Not
      // waiting would show a new definition as "not available" for a moment.
      return queryClient.invalidateQueries({ queryKey: definitionKeys.all });
    },
    [queryClient],
  );

  const create = useMutation({
    mutationFn: (draft: DefinitionDraft) => createDefinition(draft),
    onSuccess: (definition) => invalidate(definition.id),
  });

  const update = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: DefinitionPatch }) =>
      updateDefinition(id, patch),
    onSuccess: (definition) => invalidate(definition.id),
  });

  const publish = useMutation({
    mutationFn: ({ changeReason, id }: { changeReason: string; id: string }) =>
      publishDefinition(id, changeReason),
    onSuccess: (definition) => invalidate(definition.id),
  });

  const remove = useMutation({
    mutationFn: ({ changeReason, id }: { changeReason: string; id: string }) =>
      deleteDefinition(id, changeReason),
    onSuccess: (_data, { id }) => invalidate(id),
  });

  return {
    create: useCallback((draft) => create.mutateAsync(draft), [create]),
    isBusy: create.isPending || update.isPending || publish.isPending || remove.isPending,
    publish: useCallback(
      (id, changeReason) => publish.mutateAsync({ changeReason, id }),
      [publish],
    ),
    remove: useCallback(
      async (id, changeReason) => {
        await remove.mutateAsync({ changeReason, id });
      },
      [remove],
    ),
    update: useCallback((id, patch) => update.mutateAsync({ id, patch }), [update]),
  };
}
