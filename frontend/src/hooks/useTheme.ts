import { useCallback, useEffect, useState, useSyncExternalStore } from 'react';

export type ThemePreference = 'dark' | 'light' | 'system';

/** Shared with the inline script in index.html. Both read it; only this writes. */
const STORAGE_KEY = 'theme';
const DARK_QUERY = '(prefers-color-scheme: dark)';

function readPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === 'dark' || stored === 'light' ? stored : 'system';
  } catch {
    // Safari in private mode, and any browser with site data blocked, throw on
    // access rather than returning null. Following the OS is the right default
    // for someone whose preference we cannot remember anyway.
    return 'system';
  }
}

function subscribeToSystem(onChange: () => void) {
  const query = window.matchMedia(DARK_QUERY);
  query.addEventListener('change', onChange);
  return () => {
    query.removeEventListener('change', onChange);
  };
}

/**
 * The theme preference, and the one place it is written down.
 *
 * Three values, not two. "Dark" and "light" are choices; **"system" is the
 * absence of one**, and it is the default because someone who has set their OS
 * to dark has already answered this question. Collapsing it into a boolean
 * means a user who flips their laptop to dark at sunset has to come back and
 * flip this too — and it makes "I never chose" indistinguishable from "I chose
 * light", which is the state every first visit is in.
 *
 * `system` is stored as the *absence* of a key for that reason. It is also why
 * the media query is a live subscription rather than a value read once: the OS
 * can change under a tab that is already open, and it should follow.
 *
 * The resolution happens here and the *result* goes on `<html>`, so `index.css`
 * carries one dark block instead of a `prefers-color-scheme` query it would
 * then need to exempt an explicit light choice from. The same rule is
 * duplicated in the inline script in index.html, which cannot import anything
 * and has to run before React exists — keep the two in step.
 *
 * One consumer is assumed. Two would each hold their own `preference` and
 * diverge on a click, since the DOM attribute is an output here rather than the
 * source of truth; if a second one ever needs this, move the state into a
 * context rather than mounting the hook twice.
 */
export default function useTheme() {
  const [preference, setPreference] = useState<ThemePreference>(readPreference);

  // A media query is the textbook external store: something outside React with
  // its own subscription. `useState` plus an effect would be a second copy of a
  // value the browser already holds.
  const isSystemDark = useSyncExternalStore(
    subscribeToSystem,
    () => window.matchMedia(DARK_QUERY).matches,
  );

  const resolved = preference === 'system' ? (isSystemDark ? 'dark' : 'light') : preference;

  // Synchronising with something outside React, which is what effects are for.
  // Idempotent on mount: the inline script has already written this value.
  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
  }, [resolved]);

  const choose = useCallback((next: ThemePreference) => {
    setPreference(next);
    try {
      if (next === 'system') localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Not remembering the choice is a worse session, not a broken one.
    }
  }, []);

  return { choose, preference, resolved };
}
