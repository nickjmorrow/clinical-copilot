import { useState } from 'react';
import { errorMessage } from 'src/api/client';
import Button from 'src/components/Button';
import LoadFailed from 'src/components/LoadFailed';
import Loading from 'src/components/Loading';
import Page from 'src/components/Page';
import useAccessActions from 'src/hooks/useAccessActions';
import { LABEL } from 'src/styles';

/**
 * Row-level access, in its smallest honest form — SEMANTIC_LAYER.md § 19.
 *
 * Confining `scopeStates` here changes what every subsequent question can
 * see — chat, saved questions, all of it — because `app/api/deps.
 * get_current_user` is the one seam both paths read the same row through.
 * With one hardcoded dev user this proves that end to end rather than
 * implementing a permission model: pick a state, ask a question that would
 * otherwise match plenty of patients, watch it match none.
 *
 * A page of its own (`/access`), reached from the sidebar footer where
 * account-level things live — not a panel beside one conversation, because it
 * governs every conversation. What chat keeps is the part worth seeing while
 * you ask: a chip in its header whenever your scope is confined, since a
 * narrowed scope changes every answer without saying so.
 *
 * Roles are shown, not edited, here — see `AccessUpdateIn`'s docstring on the
 * backend for why granting yourself a role is a different, more sensitive
 * act than choosing which states your own queries are confined to.
 */
// `'unconfined'` is its own case rather than folded into `string[]` — an
// empty array is a real, different value on the backend (`scope_states =
// []` matches no state at all and therefore no patient), and collapsing
// "every patient" and "no patient" into the same UI state would make
// clicking Unconfined silently save the one that hides everyone.
type Draft = 'unconfined' | string[] | null;

function draftFor(pending: Draft, saved: null | string[]): 'unconfined' | string[] {
  if (pending !== null) return pending;
  return saved ?? 'unconfined';
}

export default function AccessPanel() {
  const { access, error, isBusy, isPending, retry, setScope } = useAccessActions();
  const [pending, setPending] = useState<Draft>(null);
  const [saveError, setSaveError] = useState<null | string>(null);

  if (isPending) return <Loading />;
  if (error || !access) {
    return <LoadFailed error={error} onRetry={retry} title={'Could not load your access.'} />;
  }

  const draft = draftFor(pending, access.scopeStates);
  const isUnconfined = draft === 'unconfined';
  const selected = isUnconfined ? [] : draft;
  const isDirty = pending !== null;
  // The server gates the write to curators; this only stops offering what
  // would be refused. Everyone else — every visitor to a public deployment —
  // sees their scope and cannot change it.
  const canEdit = access.roles.includes('curator');

  const toggleState = (state: string) => {
    const base = isUnconfined ? [] : draft;
    setPending(
      base.includes(state)
        ? base.filter((s) => s !== state)
        : [...base, state].sort((a, b) => a.localeCompare(b)),
    );
  };

  const save = async () => {
    setSaveError(null);
    try {
      await setScope(isUnconfined ? null : selected);
      setPending(null);
    } catch (caught) {
      setSaveError(`Could not save your access. ${errorMessage(caught)}`);
    }
  };

  return (
    <Page
      description={
        'Which patients your questions can see. Confining this to a state changes chat, saved questions and the dashboard alike — they all read the same row.'
      }
      title={'Your access'}
      width={'form'}
    >
      <div className={'mt-1'}>
        <h3 className={LABEL}>Roles</h3>
        <div className={'mt-2 flex flex-wrap gap-1.5'}>
          {access.roles.map((role) => (
            <span
              className={'rounded-full bg-ink/5 px-2 py-0.5 text-[11px] text-ink-muted'}
              key={role}
            >
              {role}
            </span>
          ))}
          {access.roles.length === 0 && <span className={'text-xs text-ink-muted'}>none</span>}
        </div>
      </div>

      <div className={'mt-5 border-t border-ink/5 pt-4'}>
        <h3 className={LABEL}>Scope</h3>

        <fieldset className={'disabled:opacity-60'} disabled={!canEdit}>
          <label className={'mt-2 flex items-center gap-2 text-xs text-ink'}>
            <input
              checked={isUnconfined}
              onChange={() => {
                setPending('unconfined');
              }}
              type={'radio'}
            />
            Unconfined — every patient
          </label>

          {access.availableStates.length === 0 ? (
            <p className={'mt-2 text-[11px] text-ink-muted'}>
              The loaded dataset has no state on any patient, so there is nothing to confine to.
            </p>
          ) : (
            <div className={'mt-1 flex flex-col gap-1'}>
              {access.availableStates.map((state) => (
                <label className={'flex items-center gap-2 text-xs text-ink'} key={state}>
                  <input
                    checked={selected.includes(state)}
                    onChange={() => {
                      toggleState(state);
                    }}
                    type={'checkbox'}
                  />
                  {state}
                </label>
              ))}
            </div>
          )}
        </fieldset>

        {saveError && <p className={'mt-2 text-xs text-danger'}>{saveError}</p>}

        {!canEdit && (
          <p className={'mt-3 text-xs text-ink-muted'}>
            Changing your scope needs the curator role.
          </p>
        )}

        {canEdit && (
          <div className={'mt-3 flex items-center gap-2'}>
            <Button disabled={!isDirty || isBusy} onClick={() => void save()} variant={'primary'}>
              {isBusy ? 'Saving…' : 'Save'}
            </Button>
            {isDirty && (
              <button
                className={'text-xs text-ink-muted hover:text-ink'}
                onClick={() => {
                  setPending(null);
                  setSaveError(null);
                }}
                type={'button'}
              >
                Cancel
              </button>
            )}
          </div>
        )}
      </div>
    </Page>
  );
}
