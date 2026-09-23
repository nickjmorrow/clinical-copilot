/**
 * Where the access token comes from.
 *
 * Deliberately not a provider SDK. The backend verifies any OIDC issuer's JWT
 * (see `backend/app/api/deps.py`), so the only thing the client has to decide is
 * how it gets one — and that answer is the one piece of auth that genuinely
 * differs between Clerk, WorkOS, Logto and the rest.
 *
 * So this is a hole of the right shape. Install your provider's React SDK, call
 * `setAccessTokenProvider` once at startup with its token getter, and every
 * request and every stream carries the header from then on:
 *
 *     // main.tsx, after the provider's own setup
 *     setAccessTokenProvider(() => auth.getToken());
 *
 * Returning null — the default — sends no header at all, which is exactly what
 * the backend wants while `OIDC_ISSUER` is unset.
 */

type AccessTokenProvider = () => Promise<null | string> | null | string;

let provider: AccessTokenProvider = () => null;

export function setAccessTokenProvider(next: AccessTokenProvider): void {
  provider = next;
}

/** The `Authorization` header, or nothing. Async because most SDKs refresh. */
export async function authHeaders(): Promise<Record<string, string>> {
  const token = await provider();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
