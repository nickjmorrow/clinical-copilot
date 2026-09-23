import { useCallback, useRef, useState } from 'react';
import useDismiss from 'src/hooks/useDismiss';

interface Props {
  isArchived: boolean;
  isPinned: boolean;
  onArchive: (isArchived: boolean) => void;
  onDelete: () => void;
  onPin: (isPinned: boolean) => void;
  onRename: () => void;
}

const ITEM =
  'block w-full rounded px-2 py-1.5 text-left text-xs text-ink transition hover:bg-ink/5';

/**
 * The per-conversation menu: rename, pin, archive, delete.
 *
 * Hand-rolled rather than a headless popover library, for the same reason the
 * router is a regex — this is one menu, and the parts a library would give you
 * that matter (Escape, click-outside, a labelled trigger) are `useDismiss` and
 * three attributes. Reach for shadcn/ui the moment there is a second one; the
 * shape here is what its `DropdownMenu` expects anyway.
 *
 * Delete confirms **in place** rather than through `window.confirm`. A native
 * confirm blocks the event loop, cannot be styled, and reads to a screen reader
 * as a page-level interruption; a second click on a button that has changed its
 * own label is the same protection without any of that. The confirmation resets
 * whenever the menu closes, so it can never be one stale click away.
 */
export default function ConversationMenu({
  isArchived,
  isPinned,
  onArchive,
  onDelete,
  onPin,
  onRename,
}: Props) {
  const [isOpen, setIsOpen] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const container = useRef<HTMLDivElement>(null);

  const close = useCallback(() => {
    setIsOpen(false);
    setIsConfirming(false);
  }, []);

  useDismiss(container, isOpen, close);

  return (
    <div className={'relative'} ref={container}>
      <button
        aria-expanded={isOpen}
        aria-haspopup={'menu'}
        aria-label={'Conversation options'}
        className={[
          'rounded p-1 text-ink-muted transition hover:bg-ink/10 hover:text-ink',
          // Hidden until the row is hovered or something inside has focus, so a
          // list of twenty is twenty titles rather than twenty titles and
          // twenty buttons. `group-focus-within` is what keeps it reachable by
          // keyboard, where there is no hover to depend on.
          isOpen
            ? 'opacity-100'
            : 'opacity-0 group-focus-within:opacity-100 group-hover:opacity-100',
        ].join(' ')}
        onClick={() => {
          setIsConfirming(false);
          setIsOpen((previous) => !previous);
        }}
        type={'button'}
      >
        <svg
          aria-hidden={'true'}
          className={'h-3.5 w-3.5'}
          fill={'currentColor'}
          viewBox={'0 0 24 24'}
        >
          <circle cx={5} cy={12} r={2} />
          <circle cx={12} cy={12} r={2} />
          <circle cx={19} cy={12} r={2} />
        </svg>
      </button>

      {isOpen && (
        <div
          className={
            'absolute top-full right-0 z-10 mt-1 w-40 rounded-lg border border-ink/10 bg-surface p-1 shadow-lg'
          }
          role={'menu'}
        >
          {!isArchived && (
            <button
              className={ITEM}
              onClick={() => {
                onRename();
                close();
              }}
              role={'menuitem'}
              type={'button'}
            >
              Rename
            </button>
          )}

          {!isArchived && (
            <button
              className={ITEM}
              onClick={() => {
                onPin(!isPinned);
                close();
              }}
              role={'menuitem'}
              type={'button'}
            >
              {isPinned ? 'Unpin' : 'Pin'}
            </button>
          )}

          <button
            className={ITEM}
            onClick={() => {
              onArchive(!isArchived);
              close();
            }}
            role={'menuitem'}
            type={'button'}
          >
            {isArchived ? 'Unarchive' : 'Archive'}
          </button>

          <button
            className={[ITEM, isConfirming ? 'text-danger' : 'text-ink-muted'].join(' ')}
            onClick={() => {
              if (!isConfirming) {
                setIsConfirming(true);
                return;
              }
              onDelete();
              close();
            }}
            role={'menuitem'}
            type={'button'}
          >
            {isConfirming ? 'Really delete?' : 'Delete'}
          </button>
        </div>
      )}
    </div>
  );
}
