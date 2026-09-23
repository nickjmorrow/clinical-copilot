import { lazy, Suspense, useEffect, useState } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router';
import ChatPage from 'src/components/ChatPage';
import Dashboard from 'src/components/Dashboard';
import Loading from 'src/components/Loading';
import SavedQuestionsPanel from 'src/components/SavedQuestionsPanel';
import Sidebar from 'src/components/Sidebar';
import { paths, PATTERNS } from 'src/paths';

// The curator side, loaded when first opened. Most people who open the app
// only ask questions, and the definitions editor — a recursive predicate
// builder and three logic editors — is the largest part of it.
const AccessPanel = lazy(() => import('src/components/AccessPanel'));
const DefinitionsEditor = lazy(() => import('src/components/DefinitionsEditor'));
const PatientBrowser = lazy(() => import('src/components/PatientBrowser'));
const UnresolvedTermsPanel = lazy(() => import('src/components/UnresolvedTermsPanel'));

/**
 * The sidebar, and the page the address names.
 *
 * Which page is on screen lives in the URL and nowhere else, so a refresh, a
 * bookmark and the Back button all land where you were, and the sidebar —
 * which reads the same address through its own `<Routes>` — cannot highlight
 * one thing while the page shows another. Every pattern comes from
 * `src/paths.ts`.
 *
 * Each page owns its title and layout; only chat has a header bar, because
 * only chat has controls that belong above its content.
 *
 * **Below `md` the sidebar is a drawer**, and the one bar every page gets there
 * is the button that opens it. The drawer is open only while the address is
 * the one it was opened on, so following any link in it — a conversation, a
 * section, "New conversation" — closes it with no handler on any of them and
 * no effect watching the location.
 */
export default function App() {
  const { pathname } = useLocation();
  const [menuOpenAt, setMenuOpenAt] = useState<null | string>(null);
  const isMenuOpen = menuOpenAt === pathname;

  // Escape closes the drawer, as it does the terms panel. The listener exists
  // only while there is something to close.
  useEffect(() => {
    if (!isMenuOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpenAt(null);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [isMenuOpen]);

  return (
    <div className={'flex h-full'}>
      <Sidebar
        isOpen={isMenuOpen}
        onClose={() => {
          setMenuOpenAt(null);
        }}
      />

      {/* Full width, not the reading column: the pane is what scrolls and what
          the rules run across, and `Column` puts the text back in the middle of
          it. A max-width here instead would park the scrollbar against the last
          word of every answer. */}
      <main className={'flex h-full min-w-0 flex-1 flex-col'}>
        <div className={'flex items-center gap-2 border-b border-ink/5 px-2 py-2 md:hidden'}>
          <button
            aria-controls={'app-menu'}
            aria-expanded={isMenuOpen}
            aria-label={'Open the menu'}
            className={'rounded-md p-2 text-ink-muted transition hover:text-ink'}
            onClick={() => {
              setMenuOpenAt(pathname);
            }}
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
          <span className={'text-sm font-semibold tracking-tight'}>Clinical Copilot</span>
        </div>

        {/* min-h-0: the page below is a flex child that scrolls inside
            itself, and without it the bar above would push it off the end
            of the screen instead of shrinking it. */}
        <div className={'flex min-h-0 flex-1 flex-col'}>
          <Suspense fallback={<Loading />}>
            <Routes>
              {/* One layout route for both chat addresses, so `ChatPage` stays
              mounted when the draft at `/` becomes `/c/<id>` — the side panel
              you had open does not close on your first message. The two
              children only match; `ChatPage` reads the id with `useParams`
              and renders the transcript itself. */}
              <Route element={<ChatPage />}>
                <Route index />
                <Route path={PATTERNS.conversation} />
              </Route>
              <Route element={<SavedQuestionsPanel />} path={PATTERNS.saved} />
              <Route element={<Dashboard />} path={PATTERNS.dashboard} />
              <Route element={<DefinitionsEditor />} path={PATTERNS.definitions} />
              <Route element={<UnresolvedTermsPanel />} path={PATTERNS.unresolved} />
              <Route element={<PatientBrowser />} path={PATTERNS.patients} />
              <Route element={<AccessPanel />} path={PATTERNS.access} />
              {/* A mistyped address lands somewhere you can do something. */}
              <Route element={<Navigate replace to={paths.draft} />} path={'*'} />
            </Routes>
          </Suspense>
        </div>
      </main>
    </div>
  );
}
