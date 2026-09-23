import { useCallback, useEffect, useRef, useState } from 'react';

/** Close enough to the bottom to count as following along. */
const PIN_THRESHOLD_PX = 120;

/**
 * At most ten scrolls a second.
 *
 * Not a micro-optimisation. The revealed text changes once per animation frame
 * while an answer streams, so an unthrottled call retargets an in-progress
 * *smooth* scroll ~60 times a second and the animation spends its life fighting
 * itself. Ten a second tracks the bottom just as closely and looks calmer.
 */
const SCROLL_THROTTLE_MS = 100;

export interface ScrollAnchor {
  containerRef: React.RefObject<HTMLDivElement | null>;
  /** False once the reader has scrolled away to read something. */
  isPinned: boolean;
  scrollToBottom: () => void;
}

/**
 * Follow a growing transcript without stealing the scrollbar.
 *
 * The naive version — scroll to the bottom whenever anything changes — fights
 * anyone who scrolls up mid-answer, which is exactly when people want to go
 * back and read something.
 *
 * The subtlety is that you cannot decide "is the reader following?" from scroll
 * events alone, because THIS HOOK generates scroll events. While a smooth
 * scroll is in flight and new text keeps arriving, the distance to the bottom
 * briefly jumps, and a naive handler reads its own animation as the user
 * leaving and switches itself off.
 *
 * So the two directions are split, and only one of them listens to intent:
 *
 *   - `scroll` may only ever RE-pin. It fires for our own scrolling too, and
 *     the worst it can do is decide we are at the bottom, which we are.
 *   - `wheel` and `touchmove` are the only things that may UNPIN, because they
 *     cannot be produced by a script. A gesture away from the bottom means the
 *     reader wants to be somewhere else.
 *
 * `revision` is whatever changes when there is new content to follow — a
 * length, a count, a concatenation. The hook does not care what it is.
 */
export default function useScrollAnchor(revision: number | string): ScrollAnchor {
  const containerRef = useRef<HTMLDivElement>(null);
  const lastScrollAt = useRef(0);
  const [isPinned, setIsPinned] = useState(true);

  const scrollToBottom = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    lastScrollAt.current = performance.now();
    container.scrollTo({ behavior: 'smooth', top: container.scrollHeight });
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const distanceFromBottom = () =>
      container.scrollHeight - container.scrollTop - container.clientHeight;

    const onScroll = () => {
      if (distanceFromBottom() <= PIN_THRESHOLD_PX) setIsPinned(true);
    };
    const onGesture = () => {
      setIsPinned(distanceFromBottom() <= PIN_THRESHOLD_PX);
    };

    container.addEventListener('scroll', onScroll, { passive: true });
    container.addEventListener('touchmove', onGesture, { passive: true });
    container.addEventListener('wheel', onGesture, { passive: true });

    return () => {
      container.removeEventListener('scroll', onScroll);
      container.removeEventListener('touchmove', onGesture);
      container.removeEventListener('wheel', onGesture);
    };
  }, []);

  useEffect(() => {
    if (!isPinned) return;

    // Leading edge plus a trailing timer, so the final update still lands at
    // the true bottom instead of being swallowed by the throttle window.
    const elapsed = performance.now() - lastScrollAt.current;
    if (elapsed >= SCROLL_THROTTLE_MS) {
      scrollToBottom();
      return;
    }

    const timer = setTimeout(scrollToBottom, SCROLL_THROTTLE_MS - elapsed);
    return () => clearTimeout(timer);
  }, [isPinned, revision, scrollToBottom]);

  return { containerRef, isPinned, scrollToBottom };
}
