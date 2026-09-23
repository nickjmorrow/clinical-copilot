import { useState } from 'react';
import StreamingText from 'src/components/StreamingText';
import { formatDuration } from 'src/format';

interface Props {
  durationMs: null | number;
  text: string;
}

/**
 * The model's reasoning for this turn.
 *
 * Open while it is happening, closed once the answer starts — which is what
 * every chat client that shows reasoning settled on, because live reasoning is
 * interesting and finished reasoning is reference material. A click overrides
 * that in either direction and sticks.
 *
 * The default is derived rather than synchronised: `override` stays null until
 * the reader actually expresses a preference, so there is no effect here
 * flipping state when the duration seals.
 *
 * Note what this is NOT: persisted. Reasoning never becomes an `event_record`
 * (see CONVENTIONS.md), so nothing here survives a refresh. Making it durable is a
 * four-file event-type change and a reversal of that decision.
 *
 * Today it does not even survive the turn: `useConversationStream` drops the
 * reasoning text as soon as the first answer token arrives, so `MessageList`
 * only ever passes a null duration and the "Thought for 2.1s" state below is
 * unreachable. It is kept because the missing piece is small and worth having —
 * the stream would have to hold the text and stamp a duration when the answer
 * starts — and because a sealed duration is the honest shape of this component
 * either way: null means "still going", a number means "done".
 */
export default function ThinkingBlock({ durationMs, text }: Props) {
  const [override, setOverride] = useState<null | boolean>(null);
  const isReasoning = durationMs === null;
  const isOpen = override ?? isReasoning;

  return (
    <div className={'max-w-[85%]'}>
      <button
        aria-expanded={isOpen}
        className={
          'flex items-center gap-1.5 rounded-md px-1 py-0.5 text-xs text-ink-muted transition hover:bg-ink/5'
        }
        onClick={() => setOverride(!isOpen)}
        type={'button'}
      >
        <svg
          aria-hidden={'true'}
          className={['h-3 w-3 transition', isOpen && 'rotate-90'].filter(Boolean).join(' ')}
          fill={'none'}
          stroke={'currentColor'}
          strokeLinecap={'round'}
          strokeLinejoin={'round'}
          strokeWidth={2}
          viewBox={'0 0 24 24'}
        >
          <polyline points={'9 18 15 12 9 6'} />
        </svg>

        <span className={isReasoning ? 'animate-pulse' : undefined}>
          {isReasoning ? 'Thinking…' : `Thought for ${formatDuration(durationMs)}`}
        </span>
      </button>

      {isOpen && (
        <div
          className={
            'mt-1 border-l-2 border-ink/10 pl-3 text-xs whitespace-pre-wrap text-ink-muted italic'
          }
        >
          {isReasoning ? <StreamingText text={text} /> : text}
        </div>
      )}
    </div>
  );
}
