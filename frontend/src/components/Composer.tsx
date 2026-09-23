import { type Ref, useImperativeHandle, useLayoutEffect, useRef, useState } from 'react';
import Column from 'src/components/Column';

interface Props {
  isStreaming: boolean;
  onSend: (content: string) => void;
  onStop: () => void;
  /** Lets the page put text into the box — a term picked from "What can I
   *  ask?" — without the box's value living anywhere but here. */
  ref?: Ref<{ insert: (text: string) => void }>;
}

/**
 * Size the box to its content. Resetting to `auto` first is load-bearing:
 * `scrollHeight` is the content height *or* the current height, whichever is
 * larger, so without the reset the box grows and never comes back down when
 * you delete a line. `max-h-40` clamps the result and the textarea's own
 * scrollbar takes over past that.
 */
function fitHeight(element: HTMLTextAreaElement) {
  element.style.height = 'auto';
  element.style.height = `${String(element.scrollHeight)}px`;
}

/**
 * The box you type in.
 *
 * **Typing and sending stay available while an answer is streaming.** The
 * server treats a new message as superseding the turn in flight — it retires
 * the old task before writing the new message, so the newest question is always
 * the one being answered — and a composer that locks itself for the duration
 * hides a capability the backend already has. See CONVENTIONS.md > Sending while one
 * is running.
 *
 * That is also why there is one button rather than two. While a turn is running
 * and the box is empty the only thing you can mean is Stop; the moment there is
 * something to send, sending *is* stopping — it cancels the old turn on its way
 * past — so a separate Stop beside it would be a second button for something
 * the first one already does. One square in one place, and it never moves.
 *
 * The textarea grows with its content rather than scrolling inside one fixed
 * line, because an input that hides the top of a three-line message reads as
 * broken.
 */
export default function Composer({ isStreaming, onSend, onStop, ref }: Props) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const submit = () => {
    const content = value.trim();
    if (!content) return;
    setValue('');
    onSend(content);
  };

  // Stop is only reachable with nothing typed; see the note above.
  const isStopping = isStreaming && !value.trim();

  // Measure, then write to the DOM — what a layout effect is for, and doing it
  // before paint is what stops the box flickering at the wrong height.
  useLayoutEffect(() => {
    if (textareaRef.current) fitHeight(textareaRef.current);
  }, [value]);

  // And again whenever the box changes width. The height depends on how the
  // text wraps, and measuring only when the text changed left an empty box
  // at its full 160px on a fresh load: it was measured once while the layout
  // around it was still settling, narrow enough for the placeholder to wrap
  // a dozen times, and nothing measured it again until you typed.
  useLayoutEffect(() => {
    const element = textareaRef.current;
    if (!element) return;
    let width = element.clientWidth;
    const observer = new ResizeObserver(() => {
      // Height changes are this code's own doing; only width is news.
      if (element.clientWidth === width) return;
      width = element.clientWidth;
      fitHeight(element);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      insert(text: string) {
        setValue((current) => {
          const before = current.trimEnd();
          return `${before ? `${before} ` : ''}${text} `;
        });
        textareaRef.current?.focus();
      },
    }),
    [],
  );

  return (
    // The rule runs the width of the pane; the box it sits under does not.
    <div className={'border-t border-ink/5'}>
      <Column className={'py-4'}>
        <div
          className={
            'flex items-end gap-2 rounded-2xl border border-ink/10 bg-surface p-2 transition focus-within:border-accent/50 focus-within:ring-2 focus-within:ring-accent/15'
          }
        >
          <textarea
            className={
              'max-h-40 flex-1 resize-none overflow-y-auto bg-transparent px-1.5 py-1 text-base leading-6 outline-none placeholder:text-ink-muted md:text-sm'
            }
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              // Enter sends, Shift+Enter makes a newline — the convention every
              // chat UI uses, and the one users will assume.
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
            placeholder={'Ask anything…'}
            ref={textareaRef}
            rows={1}
            value={value}
          />

          {isStopping ? (
            <button
              aria-label={'Stop'}
              className={
                'flex size-8 shrink-0 items-center justify-center rounded-full bg-ink/10 text-ink transition hover:bg-ink/15'
              }
              onClick={onStop}
              title={'Stop'}
              type={'button'}
            >
              <svg
                aria-hidden={'true'}
                className={'h-3 w-3'}
                fill={'currentColor'}
                viewBox={'0 0 24 24'}
              >
                <rect height={18} rx={3} width={18} x={3} y={3} />
              </svg>
            </button>
          ) : (
            <button
              aria-label={'Send'}
              className={
                'flex size-8 shrink-0 items-center justify-center rounded-full bg-accent text-on-accent transition hover:opacity-90 disabled:opacity-30'
              }
              disabled={!value.trim()}
              onClick={submit}
              title={isStreaming ? 'Send, replacing the current answer' : 'Send'}
              type={'button'}
            >
              <svg
                aria-hidden={'true'}
                className={'h-4 w-4'}
                fill={'none'}
                stroke={'currentColor'}
                strokeLinecap={'round'}
                strokeLinejoin={'round'}
                strokeWidth={2}
                viewBox={'0 0 24 24'}
              >
                <path d={'M12 19V5M5 12l7-7 7 7'} />
              </svg>
            </button>
          )}
        </div>

        {/* Said before it happens, not in a tooltip on the send button: a
            message sent mid-answer supersedes the turn in flight, and the
            text streaming above is thrown away. */}
        {isStreaming && value.trim() && (
          <p className={'mt-1.5 px-3 text-[11px] text-ink-muted'}>
            Sending now stops the answer in progress and asks this instead.
          </p>
        )}
      </Column>
    </div>
  );
}
