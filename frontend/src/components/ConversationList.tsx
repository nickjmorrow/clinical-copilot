import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { errorMessage } from 'src/api/client';
import { conversationKeys, listConversations } from 'src/api/conversations';
import ConversationRow from 'src/components/ConversationRow';
import InlineError from 'src/components/InlineError';
import NewItemLink from 'src/components/NewItemLink';
import useConversationActions from 'src/hooks/useConversationActions';
import { paths } from 'src/paths';
import { SIDEBAR_HEADING } from 'src/styles';

/**
 * Every conversation, and a way back into any of them — the sidebar's list
 * while you are in Chat.
 *
 * The titles are written by the model after the first message (see
 * `name_conversation` in the conversation service), so they are real rather
 * than "Conversation 4".
 *
 * **The archive is a second query, not a filter on the first.** The live list
 * is what `ChatPage` names the conversation on screen from, and that answer
 * should not change because somebody opened the archive. So the archive does
 * not run until it is opened. Its switch is a pair of tabs at the top of the
 * list — "Active" and "Archived" — because it changes what the list *is*, and
 * a label on the list says so where a toggle in the footer did not.
 */
export default function ConversationList() {
  const [showArchive, setShowArchive] = useState(false);
  // The conversation on screen, or null on the draft.
  const { conversationId: activeId = null } = useParams();
  const navigate = useNavigate();
  const actions = useConversationActions();

  const live = useQuery({
    // Wrapped rather than passed by reference: TanStack calls `queryFn` with a
    // context object, and `listConversations` takes an options argument that
    // the context would land in.
    queryFn: () => listConversations(),
    queryKey: conversationKeys.all,
  });
  const archived = useQuery({
    enabled: showArchive,
    queryFn: () => listConversations({ archived: true }),
    queryKey: conversationKeys.archive,
  });

  const conversations = live.data ?? [];
  const shown = showArchive ? (archived.data ?? []) : conversations;
  const current = showArchive ? archived : live;

  const open = (id: string) => {
    void navigate(paths.conversation(id));
  };
  const startNew = () => {
    void navigate(paths.draft);
  };

  // The server already ordered these — pinned first, then newest — so this
  // splits the list it was given at the boundary rather than re-sorting it.
  //
  // One array of sections rather than two blocks of JSX: the row below takes
  // five handlers, and writing them twice is how the pinned half and the
  // unpinned half drift into behaving differently.
  const pinned = shown.filter((one) => one.pinnedAt !== null);
  const sections = [
    { items: pinned, title: 'Pinned' },
    { items: shown.filter((one) => one.pinnedAt === null), title: 'Recent' },
  ].filter((section) => section.items.length > 0);

  /**
   * Leave a conversation that is about to stop being visible.
   *
   * Archiving or deleting the conversation you are reading otherwise leaves the
   * URL pointing at something the sidebar no longer lists, and the transcript
   * says "That conversation is not available" about a thing you just did on
   * purpose. Computed from the list as it stands, before the refetch lands,
   * because the answer has to be picked while the old row is still there.
   *
   * With nothing left to fall back to it lands on the draft, which is a screen
   * rather than a write — deleting your last conversation used to create one.
   */
  const leave = (id: string) => {
    if (id !== activeId) return;
    const next = conversations.find((one) => one.id !== id);
    if (next) open(next.id);
    else startNew();
  };

  return (
    <>
      <div className={'p-2'}>
        <NewItemLink
          isActive={activeId === null}
          label={'+ New conversation'}
          onClick={() => {
            // A new conversation will appear in the active list, so that is
            // where to be when it does.
            setShowArchive(false);
          }}
          to={paths.draft}
        />
      </div>

      <div className={'flex gap-1 px-2 pb-1'} role={'tablist'}>
        {[
          { isArchive: false, label: 'Active' },
          { isArchive: true, label: 'Archived' },
        ].map((tab) => (
          <button
            aria-selected={showArchive === tab.isArchive}
            className={[
              'rounded-md px-2 py-1 text-[11px] transition',
              showArchive === tab.isArchive
                ? 'bg-ink/5 font-medium text-ink'
                : 'text-ink-muted hover:text-ink',
            ].join(' ')}
            key={tab.label}
            onClick={() => {
              setShowArchive(tab.isArchive);
            }}
            role={'tab'}
            type={'button'}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <nav
        aria-label={showArchive ? 'Archived conversations' : 'Conversations'}
        className={'min-h-0 flex-1 overflow-y-auto px-2 pb-2'}
      >
        {actions.error && (
          <div className={'mb-2'}>
            <InlineError message={actions.error} onDismiss={actions.dismissError} />
          </div>
        )}

        {current.error && (
          <InlineError
            message={`Could not load your conversations. ${errorMessage(current.error)}`}
            onRetry={() => void current.refetch()}
          />
        )}

        {sections.map((section) => (
          <div key={section.title}>
            {/* Only worth a heading when there is something to tell it apart
                from. A lone "Recent" over every conversation you have is a
                label for a distinction that is not being made. */}
            {pinned.length > 0 && <p className={SIDEBAR_HEADING}>{section.title}</p>}

            {section.items.map((conversation) => (
              <ConversationRow
                conversation={conversation}
                isActive={conversation.id === activeId}
                key={conversation.id}
                onArchive={(isArchived) => {
                  actions.setArchived(conversation.id, isArchived);
                  // Only archiving takes it out of the list. Unarchiving from
                  // the archive view leaves you on it, which is the whole
                  // reason you went looking for it.
                  if (isArchived) leave(conversation.id);
                }}
                onDelete={() => {
                  actions.remove(conversation.id);
                  leave(conversation.id);
                }}
                onPin={(value) => actions.pin(conversation.id, value)}
                onRename={(title) => actions.rename(conversation.id, title)}
              />
            ))}
          </div>
        ))}

        {/* Only once the list has actually loaded: "No conversations yet"
            while the request is in flight is a false statement. */}
        {current.isSuccess && shown.length === 0 && (
          <p className={'px-2.5 py-3 text-xs text-ink-muted'}>
            {showArchive ? 'Nothing archived.' : 'No conversations yet.'}
          </p>
        )}
      </nav>
    </>
  );
}
