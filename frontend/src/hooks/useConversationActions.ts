import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useCallback, useState } from 'react';
import { errorMessage } from 'src/api/client';
import {
  conversationKeys,
  type ConversationPatch,
  deleteConversation,
  updateConversation,
} from 'src/api/conversations';

export interface ConversationActions {
  dismissError: () => void;
  /** Why the last action failed, as a sentence, until the next one starts. */
  error: null | string;
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
 * AGENTS.md: a conversation menu in a header, a keyboard shortcut, or a
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
 *
 * **A failure is reported, not dropped.** These fire from a menu and have no
 * form to put an error in, so a pin or a delete that failed used to look
 * exactly like one that had not been tried. The message names which of the
 * five it was, because the menu that asked is closed by the time it arrives.
 */
export default function useConversationActions(): ConversationActions {
  const queryClient = useQueryClient();

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: conversationKeys.all });
  }, [queryClient]);

  const [error, setError] = useState<null | string>(null);

  const patch = useMutation({
    mutationFn: ({ id, ...body }: ConversationPatch & { id: string }) =>
      updateConversation(id, body),
    onError: (caught, body) => {
      setError(`Could not ${describePatch(body)} that conversation. ${errorMessage(caught)}`);
    },
    onMutate: () => {
      setError(null);
    },
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteConversation(id),
    onError: (caught) => {
      setError(`Could not delete that conversation. ${errorMessage(caught)}`);
    },
    onMutate: () => {
      setError(null);
    },
    // Settled, not success: a delete that failed was usually preceded by
    // leaving the conversation, and the list should show it is still there.
    onSettled: invalidate,
  });

  return {
    dismissError: useCallback(() => {
      setError(null);
    }, []),
    error,
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

/** The verb for a patch, for "Could not ___ that conversation." */
function describePatch(body: ConversationPatch): string {
  if (body.title !== undefined) return 'rename';
  if (body.pinned !== undefined) return body.pinned ? 'pin' : 'unpin';
  if (body.archived !== undefined) return body.archived ? 'archive' : 'unarchive';
  return 'update';
}
