import { useState } from 'react';
import { Link, matchPath, useLocation } from 'react-router';
import useRoles from 'src/hooks/useRoles';
import { CHAT_PATTERNS, paths, PATTERNS } from 'src/paths';
import { SIDEBAR_HEADING } from 'src/styles';

interface Item {
  /** Only for curators and auditors — the server refuses everyone else. */
  isReviewOnly?: boolean;
  label: string;
  /** The patterns under which this item is the current section. */
  patterns: readonly string[];
  to: string;
}

// Two groups because there are two audiences. Asking questions and keeping
// the answers is what a clinician comes here for; the definitions, the
// backlog of terms nobody has defined, and the raw table are how a curator
// keeps those answers right. One flat list made the second group read as
// more places to ask a question.
const SECTIONS: { items: Item[]; title: null | string }[] = [
  {
    items: [
      { label: 'Chat', patterns: CHAT_PATTERNS, to: paths.draft },
      { label: 'Saved questions', patterns: [PATTERNS.saved], to: paths.saved() },
      { label: 'Dashboard', patterns: [PATTERNS.dashboard], to: paths.dashboard },
    ],
    title: null,
  },
  {
    items: [
      { label: 'Definitions', patterns: [PATTERNS.definitions], to: paths.definitions() },
      {
        isReviewOnly: true,
        label: 'Unresolved terms',
        patterns: [PATTERNS.unresolved],
        to: paths.unresolved,
      },
      { isReviewOnly: true, label: 'Patients', patterns: [PATTERNS.patients], to: paths.patients },
    ],
    title: 'Curate',
  },
];

const isUnder = (patterns: readonly string[], pathname: string) =>
  patterns.some((pattern) => matchPath(pattern, pathname) !== null);

/**
 * Every screen you can use, always visible, with the current one marked.
 *
 * Under "Curate", everyone sees Definitions — anyone may read them, and on
 * the public demo they are the thing most worth reading. The other two are
 * listed only for curators and auditors, the roles the server gates them to:
 * a link that opens onto "not for you" is a worse welcome than no link. They
 * appear once the roles have loaded, rather than flashing in and out for the
 * people who do not have them.
 *
 * "Chat" goes back to the conversation you were last in, not to a blank
 * draft. Looking at the dashboard for a moment and coming back should put
 * you where you left off; "+ New conversation" is one row further down for
 * the other case.
 */
export default function SectionNav() {
  const { pathname } = useLocation();
  const { canReview } = useRoles();
  const isInChat = isUnder(CHAT_PATTERNS, pathname);

  // The last chat address seen, updated during render rather than in an
  // effect — React's own pattern for state that follows a changing input.
  // It settles after one extra render, because the next render compares
  // equal.
  const [lastChat, setLastChat] = useState(isInChat ? pathname : paths.draft);
  if (isInChat && pathname !== lastChat) setLastChat(pathname);

  return (
    <nav aria-label={'Sections'} className={'px-2 pt-2 pb-3'}>
      {SECTIONS.map((section) => (
        <div key={section.title ?? 'ask'}>
          {section.title && <p className={SIDEBAR_HEADING}>{section.title}</p>}
          <ul className={'flex flex-col'}>
            {section.items
              .filter((item) => canReview || item.isReviewOnly !== true)
              .map((item) => {
                const isActive = isUnder(item.patterns, pathname);
                return (
                  <li key={item.label}>
                    <Link
                      aria-current={isActive ? 'page' : undefined}
                      className={[
                        'block rounded-lg px-2.5 py-1.5 text-xs transition',
                        isActive
                          ? 'bg-ink/5 font-medium text-ink'
                          : 'text-ink-muted hover:bg-ink/5 hover:text-ink',
                      ].join(' ')}
                      to={item.patterns === CHAT_PATTERNS ? lastChat : item.to}
                    >
                      {item.label}
                    </Link>
                  </li>
                );
              })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
