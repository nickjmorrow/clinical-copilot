import { apiFetch } from 'src/api/client';

/**
 * One user's roles and row-level scope — mirrors `AccessOut` in
 * backend/app/api/schemas.py. SEMANTIC_LAYER.md § 19: `scopeStates` confines
 * every clinical query this user makes (chat, saved questions, everything) to
 * patients in those states; `null` is unconfined. `availableStates` comes
 * from the loaded dataset rather than a hardcoded list of fifty.
 */
export interface Access {
  userId: string;
  roles: string[];
  scopeStates: null | string[];
  availableStates: string[];
}

export const accessKeys = {
  me: ['access', 'me'] as const,
};

export const fetchMyAccess = () => apiFetch<Access>('/access/me');

export const updateMyAccess = (scopeStates: null | string[]) =>
  apiFetch<Access>('/access/me', { body: JSON.stringify({ scopeStates }), method: 'PUT' });
