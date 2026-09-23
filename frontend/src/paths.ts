/**
 * Every URL in the app, spelled once.
 *
 * `PATTERNS` are what the router matches — `App.tsx` for the page, `Sidebar`
 * for the list beside it — and `paths` builds the addresses those patterns
 * accept. `paths.test.ts` runs every builder through react-router's own
 * `matchPath`, so a pattern and its builder cannot drift apart without a red
 * test; a typo in a hand-written `/saved/${id}` somewhere would have been a
 * blank page instead.
 *
 * `:selection` is a saved question's or a definition's id, or `new` for the
 * create form — the three states those screens always had (absent means
 * nothing chosen). `new` cannot collide with a real id because every id is a
 * UUID.
 *
 * No React here, and no router import either: this is data, and it is
 * tested as data.
 */
export const PATTERNS = {
  access: '/access',
  conversation: '/c/:conversationId',
  dashboard: '/dashboard',
  definitions: '/definitions/:selection?',
  draft: '/',
  patients: '/patients',
  saved: '/saved/:selection?',
  unresolved: '/unresolved',
} as const;

export const paths = {
  access: '/access',
  conversation: (id: string) => `/c/${id}`,
  dashboard: '/dashboard',
  definitions: (selection?: string) =>
    selection === undefined ? '/definitions' : `/definitions/${selection}`,
  draft: '/',
  patients: '/patients',
  saved: (selection?: string) => (selection === undefined ? '/saved' : `/saved/${selection}`),
  unresolved: '/unresolved',
} as const;

/** The patterns that mean "you are in Chat": the draft and any conversation. */
export const CHAT_PATTERNS = [PATTERNS.draft, PATTERNS.conversation] as const;
