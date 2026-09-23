import { Link, matchPath, Route, Routes, useLocation } from 'react-router';
import AuthorCredit from 'src/components/AuthorCredit';
import ConversationList from 'src/components/ConversationList';
import DefinitionList from 'src/components/DefinitionList';
import SavedQuestionList from 'src/components/SavedQuestionList';
import SectionNav from 'src/components/SectionNav';
import ThemeToggle from 'src/components/ThemeToggle';
import { paths, PATTERNS } from 'src/paths';

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

/**
 * The app's navigation: every screen, and the list belonging to the one you
 * are on.
 *
 * The list changes with the section — conversations in Chat, saved questions
 * in Saved questions, definitions in Definitions — and there is only ever
 * one. The conversation list used to sit beside every screen whether or not
 * it had anything to do with it, and clicking a conversation from the
 * dashboard changed the address and highlighted the row while the dashboard
 * stayed on screen. A list is now only visible where choosing from it does
 * something, and choosing from it is a link like any other.
 *
 * Its own `<Routes>`, matching the same patterns as the page's in `App`, so
 * each list reads its selection with `useParams` exactly as the page beside
 * it does.
 *
 * The footer is for things true of you and the whole app rather than of the
 * page: your access, the theme, and who built it. It renders whether or not
 * anything has loaded, so none of it disappears into an error state.
 *
 * **On a phone it is a drawer.** Beside the page it took two thirds of the
 * screen and left the chat a column one word wide, so below `md` it sits
 * off-screen until the menu button in `App`'s top bar opens it, over the page
 * with a backdrop. `isOpen` means nothing at `md` and up, where it is always
 * shown. Closed, it is `invisible` as well as moved aside, which is what takes
 * its links out of the tab order — a transform alone leaves a keyboard user
 * tabbing through a menu they cannot see.
 */
export default function Sidebar({ isOpen, onClose }: Props) {
  const { pathname } = useLocation();
  const isOnAccess = matchPath(PATTERNS.access, pathname) !== null;

  return (
    <>
      {isOpen && (
        <button
          aria-label={'Close the menu'}
          className={'fixed inset-0 z-30 cursor-default bg-ink/20 md:hidden'}
          onClick={onClose}
          tabIndex={-1}
          type={'button'}
        />
      )}
      <aside
        className={[
          'fixed inset-y-0 left-0 z-40 flex w-72 max-w-[85vw] flex-col border-r border-ink/5 bg-surface shadow-xl transition-[translate,visibility] duration-200',
          'md:visible md:static md:z-auto md:w-64 md:max-w-none md:shrink-0 md:translate-x-0 md:bg-surface-raised/40 md:shadow-none md:transition-none',
          isOpen ? 'visible translate-x-0' : 'invisible -translate-x-full',
        ].join(' ')}
        id={'app-menu'}
      >
        <div className={'flex items-center justify-between gap-2 border-b border-ink/5 px-3 py-4'}>
          <h1 className={'truncate text-sm font-semibold tracking-tight'}>Clinical Copilot</h1>
          <button
            aria-label={'Close the menu'}
            className={'-my-1 rounded-md p-1 text-ink-muted transition hover:text-ink md:hidden'}
            onClick={onClose}
            type={'button'}
          >
            <svg
              aria-hidden={'true'}
              className={'h-4 w-4'}
              fill={'none'}
              stroke={'currentColor'}
              strokeLinecap={'round'}
              strokeWidth={2}
              viewBox={'0 0 24 24'}
            >
              <path d={'M6 6l12 12M18 6L6 18'} />
            </svg>
          </button>
        </div>

        <SectionNav />

        <div className={'flex min-h-0 flex-1 flex-col border-t border-ink/5'}>
          <Routes>
            <Route element={<ConversationList />} path={PATTERNS.draft} />
            <Route element={<ConversationList />} path={PATTERNS.conversation} />
            <Route element={<SavedQuestionList />} path={PATTERNS.saved} />
            <Route element={<DefinitionList />} path={PATTERNS.definitions} />
            <Route element={null} path={'*'} />
          </Routes>
        </div>

        <div
          className={'flex flex-wrap items-center justify-between gap-2 border-t border-ink/5 p-2'}
        >
          <Link
            aria-current={isOnAccess ? 'page' : undefined}
            className={[
              'rounded-lg px-2 py-1.5 text-xs transition',
              isOnAccess ? 'bg-ink/5 font-medium text-ink' : 'text-ink-muted hover:text-ink',
            ].join(' ')}
            to={paths.access}
          >
            Your access
          </Link>

          <ThemeToggle />

          <AuthorCredit className={'w-full px-2 pb-1'} />
        </div>
      </aside>
    </>
  );
}
