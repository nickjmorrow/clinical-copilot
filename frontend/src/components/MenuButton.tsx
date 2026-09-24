interface Props {
  isOpen: boolean;
  onOpen: () => void;
}

/**
 * The button that opens the sidebar on a phone. Hidden from `md` up, where
 * the sidebar is always on screen.
 *
 * Its own component because it lives in two places: the app's top bar on
 * most pages, and the chat's own header on chat pages — where a second bar
 * above the header would stack two rows of chrome over a small screen.
 */
export default function MenuButton({ isOpen, onOpen }: Props) {
  return (
    <button
      aria-controls={'app-menu'}
      aria-expanded={isOpen}
      aria-label={'Open the menu'}
      className={
        '-ml-1 shrink-0 rounded-md p-1.5 text-ink-muted transition hover:text-ink md:hidden'
      }
      onClick={onOpen}
      type={'button'}
    >
      <svg
        aria-hidden={'true'}
        className={'h-5 w-5'}
        fill={'none'}
        stroke={'currentColor'}
        strokeLinecap={'round'}
        strokeWidth={2}
        viewBox={'0 0 24 24'}
      >
        <path d={'M4 7h16M4 12h16M4 17h16'} />
      </svg>
    </button>
  );
}
