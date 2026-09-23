import { Link, matchPath, Route, Routes, useLocation } from 'react-router';
import ConversationList from 'src/components/ConversationList';
import DefinitionList from 'src/components/DefinitionList';
import SavedQuestionList from 'src/components/SavedQuestionList';
import SectionNav from 'src/components/SectionNav';
import ThemeToggle from 'src/components/ThemeToggle';
import { paths, PATTERNS } from 'src/paths';

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
 * page: your access, and the theme. It renders whether or not anything has
 * loaded, so neither disappears into an error state.
 */
export default function Sidebar() {
  const { pathname } = useLocation();
  const isOnAccess = matchPath(PATTERNS.access, pathname) !== null;

  return (
    <aside className={'flex w-64 shrink-0 flex-col border-r border-ink/5 bg-surface-raised/40'}>
      <div className={'flex items-center border-b border-ink/5 px-3 py-4'}>
        <h1 className={'truncate text-sm font-semibold tracking-tight'}>Clinical Copilot</h1>
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

      <div className={'flex items-center justify-between gap-2 border-t border-ink/5 p-2'}>
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
      </div>
    </aside>
  );
}
