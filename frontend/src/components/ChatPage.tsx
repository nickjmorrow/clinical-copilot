import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { accessKeys, fetchMyAccess } from 'src/api/access';
import { conversationKeys, getConversation, listConversations } from 'src/api/conversations';
import Button from 'src/components/Button';
import Chat from 'src/components/Chat';
import ClinicalContextPanel from 'src/components/ClinicalContextPanel';
import Column from 'src/components/Column';
import EmptyState from 'src/components/EmptyState';
import { paths } from 'src/paths';

// Tailwind's `lg`, where the terms panel sits beside the chat rather than
// over it. Kept next to the one place that has to ask.
const WIDE = '(min-width: 1024px)';

/** How a confined scope reads in the chip, or null when there is no chip. */
function scopeLabel(states: null | string[]): null | string {
  if (states === null) return null;
  if (states.length === 0) return 'No states in scope';
  if (states.length <= 2) return `Only ${states.join(', ')}`;
  return `Only ${String(states.length)} states`;
}

/**
 * Chat: the header naming the conversation, the transcript, and the "What can
 * I ask?" panel. Mounted by one layout route over both `/` and `/c/:id` (see
 * `App.tsx`), so it stays mounted when a draft becomes a conversation and the
 * panel you had open stays open.
 *
 * **The panel is beside the chat on a wide window and over it on a narrow
 * one.** It used to be `hidden` below 1024px while its button still toggled —
 * "Hide terms" with nothing shown. Over the chat it gets a backdrop, a close
 * button of its own, and Escape; a term picked from it closes it, because on
 * a narrow window the box it just typed into is underneath.
 *
 * **A confined scope is shown, always.** Choosing which states your questions
 * see lives on its own page now, but its effect is on every answer here, and
 * an answer that silently covers fewer patients than you think is the worst
 * kind — so while it is confined, the header says so and links to where it
 * can be changed.
 *
 * A conversation id in the URL is used **verbatim** — it is deliberately not
 * checked against the list first. A link someone sent you, or one to a
 * conversation the list has not caught up with, should be attempted and
 * allowed to fail with a real message; quietly falling back to the newest
 * conversation would turn "you cannot open this" into "here is something
 * else", which is worse.
 *
 * `/` is not a missing id, it is the **draft**: an empty transcript and a
 * composer, with no row behind it until a message is sent. See CONVENTIONS.md >
 * Starting one.
 */
export default function ChatPage() {
  const { conversationId = null } = useParams();
  const navigate = useNavigate();
  const composer = useRef<{ insert: (text: string) => void }>(null);

  // Local, not server state: whether the panel is open is this browser's
  // business and nothing else needs to know.
  const [isTermsOpen, setIsTermsOpen] = useState(false);

  const {
    data: conversations,
    error,
    refetch,
  } = useQuery({
    // Wrapped rather than passed by reference: TanStack calls `queryFn` with a
    // context object, and `listConversations` takes an options argument that
    // the context would land in.
    queryFn: () => listConversations(),
    queryKey: conversationKeys.all,
  });
  const access = useQuery({ queryFn: fetchMyAccess, queryKey: accessKeys.me });

  // The open conversation's own record, not a lookup in the list: the list
  // is the active one only, so an archived conversation was titled "New
  // conversation". Same key as `Chat`'s transcript, so this is that fetch,
  // not a second one.
  const { data: open } = useQuery({
    enabled: conversationId !== null,
    queryFn: () => (conversationId === null ? null : getConversation(conversationId)),
    queryKey: conversationKeys.detail(conversationId ?? 'draft'),
  });
  const title =
    conversationId === null
      ? 'New conversation'
      : (open?.title ?? conversations?.find((one) => one.id === conversationId)?.title ?? '');
  const scope = access.data ? scopeLabel(access.data.scopeStates) : null;

  // Escape closes the panel. Synchronising with the document is what an
  // effect is for, and the listener only exists while there is something to
  // close.
  useEffect(() => {
    if (!isTermsOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsTermsOpen(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [isTermsOpen]);

  const pickTerm = (term: string) => {
    composer.current?.insert(term);
    if (!window.matchMedia(WIDE).matches) setIsTermsOpen(false);
  };

  return (
    <div className={'flex h-full min-w-0'}>
      <div className={'flex min-w-0 flex-1 flex-col'}>
        <header className={'border-b border-ink/5'}>
          <Column className={'flex items-center gap-3 py-4'}>
            <h2
              className={
                'min-w-0 flex-1 truncate text-sm font-medium tracking-tight text-ink-muted'
              }
            >
              {title}
            </h2>
            {scope && access.data && (
              <Link
                className={[
                  'shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-medium transition',
                  access.data.scopeStates?.length === 0
                    ? 'border-danger/40 text-danger'
                    : 'border-accent/30 bg-accent/10 text-ink hover:border-accent/50',
                ].join(' ')}
                title={
                  access.data.scopeStates?.length === 0
                    ? 'Your scope includes no states, so every answer will match nobody. Change it in Your access.'
                    : `Your questions only see patients in: ${(access.data.scopeStates ?? []).join(', ')}. Change it in Your access.`
                }
                to={paths.access}
              >
                {scope}
              </Link>
            )}
            <Button
              aria-expanded={isTermsOpen}
              className={'shrink-0'}
              onClick={() => {
                setIsTermsOpen((open) => !open);
              }}
              size={'sm'}
            >
              {isTermsOpen ? 'Hide terms' : 'What can I ask?'}
            </Button>
          </Column>
        </header>

        {error && conversationId === null ? (
          // Only worth saying here. With an id in the URL the transcript does
          // its own fetching and reports its own failure, and a broken sidebar
          // is not a reason to hide a conversation that loaded.
          <EmptyState detail={error.message} title={'Could not reach the server.'}>
            <Button onClick={() => void refetch()} variant={'primary'}>
              Try again
            </Button>
          </EmptyState>
        ) : (
          // `key` is load-bearing: it remounts Chat when the conversation
          // changes, which resets the stream state that belongs to the old
          // one. React's own answer to "reset all state when a prop changes".
          //
          // A draft keys as `new`, so the first message — which turns `/`
          // into `/c/<id>` — remounts too. That is why `Chat` hands the id it
          // just created over *after* seeding the cache the remount reads, and
          // why the address is replaced rather than pushed: the draft became
          // this conversation, and Back should not land on an empty composer.
          <Chat
            composerRef={composer}
            conversationId={conversationId}
            key={conversationId ?? 'new'}
            onCreated={(id) => {
              void navigate(paths.conversation(id), { replace: true });
            }}
          />
        )}
      </div>

      {isTermsOpen && (
        <>
          {/* Narrow windows only: the panel covers the chat, so a click
              anywhere else is a request to put it away. */}
          <button
            aria-label={'Close what you can ask'}
            className={'fixed inset-0 z-20 cursor-default bg-ink/20 lg:hidden'}
            onClick={() => {
              setIsTermsOpen(false);
            }}
            tabIndex={-1}
            type={'button'}
          />
          <aside
            className={
              'fixed inset-y-0 right-0 z-30 w-80 max-w-[85vw] border-l border-ink/5 bg-surface shadow-xl lg:static lg:z-auto lg:max-w-none lg:shrink-0 lg:shadow-none'
            }
          >
            <ClinicalContextPanel
              onClose={() => {
                setIsTermsOpen(false);
              }}
              onPickTerm={pickTerm}
            />
          </aside>
        </>
      )}
    </div>
  );
}
