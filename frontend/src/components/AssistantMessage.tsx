import Bubble from 'src/components/Bubble';
import CopyButton from 'src/components/CopyButton';
import LazyMarkdown from 'src/components/LazyMarkdown';

interface Props {
  /** The end of an answer, rather than a line said on the way to a tool. */
  isAnswerEnd: boolean;
  text: string;
}

/**
 * A finished answer: the markdown, and the one affordance people reach for.
 *
 * Copy is offered over the whole message rather than only over a code block,
 * because the thing someone wants to paste into a ticket is usually the prose
 * and the snippet together. It copies the markdown SOURCE, not the rendered
 * text — that is what survives being pasted somewhere else that renders it.
 *
 * Only at the end of an answer. "I'll look that up." before a tool call is
 * not something anyone copies, and its button row — which occupies its space
 * even while invisible, so revealing it on hover does not shift the
 * transcript under the pointer — was a blank gap between that line and the
 * result.
 *
 * `focus-within` keeps it reachable without a mouse, since `opacity-0` leaves
 * it in the tab order; `pointer-coarse` shows it outright on a touch screen,
 * where there is no hover to reveal it.
 */
export default function AssistantMessage({ isAnswerEnd, text }: Props) {
  return (
    <Bubble role={'assistant'}>
      <div className={'group'}>
        <LazyMarkdown text={text} />

        {isAnswerEnd && (
          <div
            className={
              'mt-1 -ml-1.5 opacity-0 transition group-hover:opacity-100 focus-within:opacity-100 pointer-coarse:opacity-100'
            }
          >
            <CopyButton text={text} />
          </div>
        )}
      </div>
    </Bubble>
  );
}
