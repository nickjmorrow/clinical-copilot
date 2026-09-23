import type { ConversationEvent } from 'src/api/conversations';
import AuthorCredit from 'src/components/AuthorCredit';
import Bubble from 'src/components/Bubble';
import Column from 'src/components/Column';
import StarterQuestions from 'src/components/StarterQuestions';
import StreamingMarkdown from 'src/components/StreamingMarkdown';
import ThinkingBlock from 'src/components/ThinkingBlock';
import TurnItemView from 'src/components/TurnItemView';
import useScrollAnchor from 'src/hooks/useScrollAnchor';
import { toTurnItems } from 'src/turns';

/**
 * The three dots shown while a leg of the turn has produced nothing yet.
 *
 * Written out as whole class strings rather than computed, because Tailwind
 * finds its classes by scanning the source as text: a template literal building
 * `[animation-delay:${n}ms]` produces nothing at build time. `motion-reduce` is
 * on the shared part of the string below.
 */
const DOT_DELAYS = [
  'motion-reduce:animate-none',
  '[animation-delay:150ms] motion-reduce:animate-none',
  '[animation-delay:300ms] motion-reduce:animate-none',
];

interface Props {
  error: null | string;
  events: ConversationEvent[];
  isStreaming: boolean;
  /** Tokens arriving right now, not yet replaced by a durable event. */
  liveText: string;
  /** Asks a starter question on the reader's behalf. Empty state only. */
  onAsk: (question: string) => void;
  thinkingText: string;
}

/**
 * The transcript.
 *
 * Everything durable arrives as `events` and folds through `toTurnItems`;
 * `liveText` is the one thing on screen that is not yet a row, and it is
 * replaced by the `assistant_message` that follows it.
 *
 * Two things here are about reading rather than about data.
 *
 * Following the answer is `useScrollAnchor`, which stops at the first gesture
 * away from the bottom instead of dragging the reader back — and offers the way
 * back rather than taking it. The button only exists while it is needed, which
 * is also the only time it is not in the way.
 *
 * The `aria-live` region wraps the DURABLE items and nothing else. A live
 * region around the streaming preview would re-announce a growing string many
 * times a second, which is unusable; letting the finished `assistant_message`
 * announce itself once, a moment later, says the same thing properly. The
 * preview and the reasoning are marked hidden for that reason, not because they
 * do not matter.
 */
export default function MessageList({
  error,
  events,
  isStreaming,
  liveText,
  onAsk,
  thinkingText,
}: Props) {
  const items = toTurnItems(events);

  // Anything that means there is new content to follow. The hook does not care
  // what the value is, only that it changes.
  const { containerRef, isPinned, scrollToBottom } = useScrollAnchor(
    `${items.length}:${liveText.length}:${thinkingText.length}`,
  );

  // Nothing has come back yet for this leg of the turn: no reasoning to show
  // and no answer started. After a tool call this can happen a second time.
  const isWaiting = isStreaming && !thinkingText && !liveText;

  return (
    <div className={'relative flex min-h-0 flex-1 flex-col'}>
      {/* The scroll container is the whole pane, so the scrollbar rides the edge
          of the window instead of the edge of the text. `Column` re-centres
          what is in it, and `scrollbar-gutter` reserves the bar's width on both
          sides so that centre is the same one the composer below uses — on the
          platforms where a scrollbar takes up space, which macOS is not. */}
      <div
        className={
          'flex min-h-0 flex-1 [scrollbar-gutter:stable_both-edges] flex-col overflow-y-auto'
        }
        ref={containerRef}
      >
        <Column className={'flex min-h-full flex-col gap-6 py-6'}>
          {items.length === 0 && !isStreaming && (
            <div className={'m-auto max-w-md text-center sm:px-4'}>
              <p className={'text-sm font-medium text-ink'}>
                Ask a clinical question about this hospital&rsquo;s patients.
              </p>
              <p className={'mt-2 text-xs text-ink-muted'}>
                Questions are answered using this hospital&rsquo;s own definitions of clinical
                terms, and every answer shows which ones it used.
              </p>
              <StarterQuestions onAsk={onAsk} />
              <p className={'mt-5 text-xs text-ink-muted'}>
                All patient data here is synthetic. This is a demonstration, not a clinical decision
                support tool.
              </p>
              <AuthorCredit className={'mt-2'} />
            </div>
          )}

          <div aria-live={'polite'} className={'flex flex-col gap-6'}>
            {items.map((item) => (
              <TurnItemView item={item} key={item.key} />
            ))}
          </div>

          {isStreaming && thinkingText && (
            <div aria-hidden={'true'}>
              {/* Null duration: while this is on screen the model is still
                reasoning. The stream drops the text the moment the answer
                starts, so there is no "thought for 2s" state to reach. */}
              <ThinkingBlock durationMs={null} text={thinkingText} />
            </div>
          )}

          {/* Tokens, ahead of the row that will replace them. There is only ever
            one of these: the durable assistant_message clears it as it arrives. */}
          {liveText && (
            <div aria-hidden={'true'}>
              <Bubble role={'assistant'}>
                <StreamingMarkdown text={liveText} />
              </Bubble>
            </div>
          )}

          {isWaiting && (
            <div className={'flex items-center gap-1.5 px-1'} role={'status'}>
              <span className={'sr-only'}>Working on it</span>
              {DOT_DELAYS.map((delay) => (
                <span
                  aria-hidden={'true'}
                  className={['h-1.5 w-1.5 animate-pulse rounded-full bg-ink-muted', delay].join(
                    ' ',
                  )}
                  key={delay}
                />
              ))}
            </div>
          )}

          {error && (
            <div
              className={
                'rounded-lg border border-danger/20 bg-danger/10 px-4 py-2.5 text-sm text-danger'
              }
              role={'alert'}
            >
              {error}
            </div>
          )}
        </Column>
      </div>

      {!isPinned && (
        <button
          className={
            'absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-ink/10 bg-surface-raised px-3 py-1.5 text-xs text-ink-muted shadow-sm transition hover:text-ink'
          }
          onClick={scrollToBottom}
          type={'button'}
        >
          <svg
            aria-hidden={'true'}
            className={'h-3 w-3'}
            fill={'none'}
            stroke={'currentColor'}
            strokeLinecap={'round'}
            strokeLinejoin={'round'}
            strokeWidth={2}
            viewBox={'0 0 24 24'}
          >
            <polyline points={'6 9 12 15 18 9'} />
          </svg>
          Jump to latest
        </button>
      )}
    </div>
  );
}
