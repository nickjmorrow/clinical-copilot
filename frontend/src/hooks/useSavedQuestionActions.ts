import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useCallback } from 'react';
import {
  createSavedQuestion,
  deleteSavedQuestion,
  type SavedQuestion,
  type SavedQuestionDraft,
  savedQuestionKeys,
} from 'src/api/savedQuestions';

export interface SavedQuestionActions {
  isBusy: boolean;
  create: (draft: SavedQuestionDraft) => Promise<SavedQuestion>;
  remove: (id: string) => Promise<void>;
}

/**
 * Create and delete — the two things done to a saved question from more than
 * one place (`SavedQuestionForm`; `remove` is also reachable from
 * `SavedQuestionDetail`). Not `list`; the panel owns that query directly, the
 * same split `useDefinitionActions` makes for `preview`. Not `run` either —
 * it has exactly one caller (`SavedQuestionDetail`), which owns a
 * `useMutation` for it directly rather than going through a wrapper only it
 * ever called.
 */
export default function useSavedQuestionActions(): SavedQuestionActions {
  const queryClient = useQueryClient();

  // Returned, so the mutation waits for the refetch: the caller navigates to
  // the new question (or away from a deleted one) next, and the page it lands
  // on reads this list.
  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: savedQuestionKeys.all }),
    [queryClient],
  );

  const create = useMutation({
    mutationFn: (draft: SavedQuestionDraft) => createSavedQuestion(draft),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteSavedQuestion(id),
    onSuccess: invalidate,
  });

  return {
    create: useCallback((draft) => create.mutateAsync(draft), [create]),
    isBusy: create.isPending || remove.isPending,
    remove: useCallback(
      async (id) => {
        await remove.mutateAsync(id);
      },
      [remove],
    ),
  };
}
