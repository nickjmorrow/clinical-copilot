import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback } from 'react';
import { type Access, accessKeys, fetchMyAccess, updateMyAccess } from 'src/api/access';

export interface AccessActions {
  access?: Access;
  error: Error | null;
  isBusy: boolean;
  isPending: boolean;
  retry: () => void;
  setScope: (scopeStates: null | string[]) => Promise<Access>;
}

/**
 * Read and write the caller's own row-level scope. One query, one mutation —
 * small enough that `AccessPanel` could hold this inline, but pulled out
 * anyway so the panel stays layout and this stays the one place that knows
 * `access.me` is the query key to invalidate after a write.
 */
export default function useAccessActions(): AccessActions {
  const queryClient = useQueryClient();

  const query = useQuery({ queryFn: fetchMyAccess, queryKey: accessKeys.me });

  const update = useMutation({
    mutationFn: (scopeStates: null | string[]) => updateMyAccess(scopeStates),
    onSuccess: (access) => {
      queryClient.setQueryData(accessKeys.me, access);
    },
  });

  return {
    access: query.data,
    error: query.error,
    isBusy: update.isPending,
    isPending: query.isPending,
    retry: useCallback(() => void query.refetch(), [query]),
    setScope: useCallback((scopeStates) => update.mutateAsync(scopeStates), [update]),
  };
}
