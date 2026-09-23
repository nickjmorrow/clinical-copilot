import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useCallback } from 'react';
import {
  conversationKeys,
  type ConversationPatch,
  deleteConversation,
  updateConversation,
} from 'src/api/conversations';

export interface ConversationActions {
  isBusy: boolean;
  pin: (id: string, isPinned: boolean) => void;
  remove: (id: string) => void;
  rename: (id: string, title: string) => void;
  setArchived: (id: string, isArchived: boolean) => void;
}

/**
 * The four things you can do to a conversation from outside it.
 *
 * A hook rather than four `useMutation` calls in the sidebar, by the test in
 * CONVENTIONS.md: a conversation menu in a header, a keyboard shortcut, or a
 * right-click on a transcript would all want these unchanged. What they share
 * is not the four endpoints — it is the invalidation, which has to cover the
 * list, the archive *and* the open transcript, because archiving the
 * conversation you are reading changes all three.
 *
 * Deliberately not optimistic. Every one of these is a single field on a row
 * the server re-orders, and an optimistic pin has to reimplement that ordering
 * in TypeScript to avoid a visible jump when the refetch lands. The round trip
 * is one local request; reimplementing `order by pinned_at desc nulls last` is
 * forever.
 *
 * Two mutation instances, not five: patching and deleting are the only two
 * shapes. `pin`, `rename` and `setArchived` are the same request with a
 * different body, and giving each its own `useMutation` would only give each
 * its own `isPending` for no one to read.
 */
export default function useConversationActions(): ConversationActions {
  const queryClient = useQueryClient();

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: conversationKeys.all });
  }, [queryClient]);

  const patch = useMutation({
    mutationFn: ({ id, ...body }: ConversationPatch & { id: string }) =>
      updateConversation(id, body),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteConversation(id),
    onSuccess: invalidate,
  });

  return {
    isBusy: patch.isPending || remove.isPending,
    pin: useCallback((id, isPinned) => patch.mutate({ id, pinned: isPinned }), [patch]),
    remove: useCallback((id) => remove.mutate(id), [remove]),
    rename: useCallback((id, title) => patch.mutate({ id, title }), [patch]),
    setArchived: useCallback(
      (id, isArchived) => patch.mutate({ archived: isArchived, id }),
      [patch],
    ),
  };
}
