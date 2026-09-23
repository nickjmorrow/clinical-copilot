import { matchPath } from 'react-router';
import { describe, expect, it } from 'vitest';
import { CHAT_PATTERNS, paths, PATTERNS } from 'src/paths';

const ID = '714a4d94-7568-49a2-b1a0-be30e427bae2';

// [what the builder produced, the pattern that must accept it, the params it
// must come back with]. `matchPath` is the router's own matcher, so this is
// the same question the router asks.
const CASES: [string, string, Record<string, string | undefined>][] = [
  [paths.draft, PATTERNS.draft, {}],
  [paths.conversation(ID), PATTERNS.conversation, { conversationId: ID }],
  [paths.saved(), PATTERNS.saved, { selection: undefined }],
  [paths.saved('new'), PATTERNS.saved, { selection: 'new' }],
  [paths.saved(ID), PATTERNS.saved, { selection: ID }],
  [paths.dashboard, PATTERNS.dashboard, {}],
  [paths.definitions(), PATTERNS.definitions, { selection: undefined }],
  [paths.definitions('new'), PATTERNS.definitions, { selection: 'new' }],
  [paths.definitions(ID), PATTERNS.definitions, { selection: ID }],
  [paths.unresolved, PATTERNS.unresolved, {}],
  [paths.patients, PATTERNS.patients, {}],
  [paths.access, PATTERNS.access, {}],
];

describe('every path a builder makes is one its pattern accepts', () => {
  it.each(CASES)('%s', (path, pattern, params) => {
    const match = matchPath(pattern, path);
    expect(match, `${pattern} does not match ${path}`).not.toBeNull();
    expect({ ...match?.params }).toEqual(params);
  });
});

describe('no path is claimed by two patterns', () => {
  const patterns = Object.values(PATTERNS);

  it.each(CASES)('%s', (path) => {
    const claimants = patterns.filter((pattern) => matchPath(pattern, path) !== null);
    expect(claimants).toHaveLength(1);
  });
});

const isChat = (path: string) => CHAT_PATTERNS.some((pattern) => matchPath(pattern, path) !== null);

describe('CHAT_PATTERNS', () => {
  it('covers the draft and a conversation, and nothing else', () => {
    expect(isChat(paths.draft)).toBe(true);
    expect(isChat(paths.conversation(ID))).toBe(true);
    expect(isChat(paths.dashboard)).toBe(false);
    expect(isChat(paths.saved(ID))).toBe(false);
  });
});
