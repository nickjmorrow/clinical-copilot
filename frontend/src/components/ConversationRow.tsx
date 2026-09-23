import { useRef, useState } from 'react';
import { Link } from 'react-router';
import type { Conversation } from 'src/api/conversations';
import ConversationMenu from 'src/components/ConversationMenu';
import { paths } from 'src/paths';

interface Props {
  conversation: Conversation;
  isActive: boolean;
  onArchive: (isArchived: boolean) => void;
  onDelete: () => void;
  onPin: (isPinned: boolean) => void;
  onRename: (title: string) => void;
}

/**
 * One conversation in the sidebar, and everything you can do to it.
 *
 * Renaming happens in place. The row becomes an input holding the current
 * title, which is what makes "fix a typo in the name the model chose" one
 * keystroke rather than retyping the whole thing — a dialog would be more code
 * and strictly worse at the common case.
 *
 * Commit on Enter or blur, abandon on Escape. Blur committing is the part worth
 * arguing about: an input that silently discards what you typed because you
 * clicked away is the more surprising of the two, and Escape is there for
 * people who meant to abandon.
 */
export default function ConversationRow({
  conversation,
  isActive,
  onArchive,
  onDelete,
  onPin,
  onRename,
}: Props) {
  const [draft, setDraft] = useState<null | string>(null);
  // A ref rather than state: it is read inside the blur that the same keystroke
  // causes, and a state update would not have landed by then.
  const isAbandoning = useRef(false);
  const title = conversation.title ?? 'New conversation';

  const commit = () => {
    const next = draft?.trim();
    setDraft(null);
    // An unchanged title is not a rename. Sending it anyway would set
    // `title_custom` and quietly stop the model ever naming this one.
    if (next && next !== conversation.title) onRename(next);
  };

  if (draft !== null) {
    return (
      <input
        aria-label={'Conversation title'}
        // The input only exists because the user just chose "Rename". Not
        // focusing it costs a second deliberate click to do the one thing it
        // is for, which is worse for everyone including the people the rule
        // protects — the exception the rule's own docs describe.
        // eslint-disable-next-line jsx-a11y/no-autofocus
        autoFocus
        className={
          'w-full rounded-lg border border-accent/40 bg-surface px-2.5 py-2 text-xs text-ink outline-none'
        }
        onBlur={() => {
          // Both keys blur, and only this decides which one it was. Handling
          // Escape by clearing the draft directly would unmount a focused
          // input, and a browser that fires `blur` on removal then commits the
          // text the user just abandoned — a race that depends on the engine.
          if (isAbandoning.current) {
            isAbandoning.current = false;
            setDraft(null);
            return;
          }
          commit();
        }}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') event.currentTarget.blur();
          else if (event.key === 'Escape') {
            isAbandoning.current = true;
            event.currentTarget.blur();
            // Otherwise Escape also closes whatever is listening above this.
            event.stopPropagation();
          }
        }}
        value={draft}
      />
    );
  }

  return (
    <div
      className={[
        'group flex items-center gap-1 rounded-lg pr-1 transition',
        isActive ? 'bg-accent/10' : 'hover:bg-ink/5',
      ].join(' ')}
    >
      {/* A link, so cmd-click opens the conversation in a new tab. */}
      <Link
        aria-current={isActive ? 'page' : undefined}
        className={[
          'min-w-0 flex-1 truncate rounded-lg px-2.5 py-2 text-left text-xs transition',
          isActive ? 'font-medium text-ink' : 'text-ink-muted group-hover:text-ink',
        ].join(' ')}
        to={paths.conversation(conversation.id)}
      >
        {title}
      </Link>

      <ConversationMenu
        isArchived={conversation.archivedAt !== null}
        isPinned={conversation.pinnedAt !== null}
        onArchive={onArchive}
        onDelete={onDelete}
        onPin={onPin}
        onRename={() => setDraft(title)}
      />
    </div>
  );
}
