import { Navigate, Route, Routes } from 'react-router';
import AccessPanel from 'src/components/AccessPanel';
import ChatPage from 'src/components/ChatPage';
import Dashboard from 'src/components/Dashboard';
import DefinitionsEditor from 'src/components/DefinitionsEditor';
import PatientBrowser from 'src/components/PatientBrowser';
import SavedQuestionsPanel from 'src/components/SavedQuestionsPanel';
import Sidebar from 'src/components/Sidebar';
import UnresolvedTermsPanel from 'src/components/UnresolvedTermsPanel';
import { paths, PATTERNS } from 'src/paths';

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
 */
export default function App() {
  return (
    <div className={'flex h-full'}>
      <Sidebar />

      {/* Full width, not the reading column: the pane is what scrolls and what
          the rules run across, and `Column` puts the text back in the middle of
          it. A max-width here instead would park the scrollbar against the last
          word of every answer. */}
      <main className={'flex h-full min-w-0 flex-1 flex-col'}>
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
      </main>
    </div>
  );
}
