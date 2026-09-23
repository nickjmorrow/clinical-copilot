import { useEffect, useState } from 'react';

/**
 * Text that is still arriving, revealed at a steady pace.
 *
 * WHY THIS EXISTS: tokens do not arrive evenly. One SSE frame carries several
 * words, React batches every state update that lands in the same tick, and this
 * app adds a hop (worker -> NOTIFY -> bus -> SSE). Render straight from the
 * stream and you get nothing, nothing, then half a sentence at once — which
 * reads as jittery rather than fast, however quick it actually is.
 *
 * So the arrival rate and the reveal rate are separated. Text accumulates in
 * the argument; this walks toward it one animation frame at a time.
 *
 * The step is PROPORTIONAL to how far behind it is, which is what keeps it
 * honest: a fixed characters-per-second reveal either lags further and further
 * behind a fast model, or is set so high it is not smoothing anything. Falling
 * behind makes it speed up, so it converges instead of drifting.
 *
 * It is a hook rather than part of a component because two surfaces need it —
 * the answer (`StreamingMarkdown`) and the reasoning (`StreamingText`) — and
 * they render the result completely differently.
 */

// Reveal 1/8th of the backlog each frame. At 60fps a typical stream (~250
// characters a second, arriving in 25-character frames) becomes 6-character
// steps about 150ms behind the model — smooth, and close enough that the
// durable row replacing it is not a visible jump.
//
// There is deliberately no upper bound on the step. An earlier version capped
// it at 8 characters per frame; simulating it showed the cap did nothing in
// normal conditions (the proportional term is already below it) and broke the
// one case it was meant for — against a source faster than the cap, the
// backlog grew without limit and ended two seconds behind, finishing in one
// enormous snap. Proportional alone always converges, because falling behind is
// exactly what makes it speed up.
const CATCH_UP_DIVISOR = 8;

// So the last few characters never stall.
const MIN_CHARS_PER_FRAME = 1;

export default function useRevealedText(text: string): string {
  const [shown, setShown] = useState(text);

  useEffect(() => {
    if (shown === text) return;

    // One frame, one step. The resulting render schedules the next, and the
    // chain stops on its own when it catches up.
    //
    // Everything happens inside the callback, including the snap below. Setting
    // state synchronously in an effect body is a cascading render, and the
    // frame it costs to do it here instead is ~16ms on a path that is already
    // frame-paced — invisible, and it keeps this to one code path rather than
    // two.
    //
    // requestAnimationFrame pauses in a background tab, so a tab left in the
    // background falls behind and catches up on return — correct, and cheaper
    // than animating something nobody is looking at.
    const frame = requestAnimationFrame(() => {
      // The text was replaced rather than extended — a durable event landing,
      // or a new turn starting. There is nothing to animate toward, so snap.
      if (!text.startsWith(shown)) {
        setShown(text);
        return;
      }

      const remaining = text.length - shown.length;
      const step = Math.max(MIN_CHARS_PER_FRAME, Math.ceil(remaining / CATCH_UP_DIVISOR));
      setShown(text.slice(0, shown.length + step));
    });

    return () => cancelAnimationFrame(frame);
  }, [shown, text]);

  return shown;
}
