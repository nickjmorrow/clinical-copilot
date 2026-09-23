import { useQuery } from '@tanstack/react-query';
import { accessKeys, fetchMyAccess } from 'src/api/access';

export interface Roles {
  /** May change the definitions, and preview a change against patient data. */
  canCurate: boolean;
  /** May see the curator surfaces that are not open to everyone: the
   *  unresolved-terms report and the raw patient table. */
  canReview: boolean;
  /** False until the roles have loaded — so nothing flashes in, or out. */
  isKnown: boolean;
}

/**
 * What the current user may do, from the same `access.me` row every page reads.
 *
 * A hook rather than `roles.includes('curator')` at each call site, because
 * the same two questions are asked by the sidebar, the definitions list and
 * the definition form, and the server is the one that enforces the answer —
 * this only decides what is worth showing.
 */
export default function useRoles(): Roles {
  const { data } = useQuery({ queryFn: fetchMyAccess, queryKey: accessKeys.me });
  const roles = data?.roles ?? [];
  const canCurate = roles.includes('curator');
  return {
    canCurate,
    canReview: canCurate || roles.includes('auditor'),
    isKnown: data !== undefined,
  };
}
