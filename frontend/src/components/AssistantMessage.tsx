import Bubble from 'src/components/Bubble';
import CopyButton from 'src/components/CopyButton';
import Markdown from 'src/components/Markdown';

interface Props {
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
 * The button occupies its row even while invisible, so revealing it on hover
 * does not shift the transcript under the pointer. `focus-within` is what keeps
 * it reachable without a mouse, since `opacity-0` leaves it in the tab order.
 */
export default function AssistantMessage({ text }: Props) {
  return (
    <Bubble role={'assistant'}>
      <div className={'group'}>
        <Markdown text={text} />

        <div
          className={
            'mt-1 -ml-1.5 opacity-0 transition group-hover:opacity-100 focus-within:opacity-100'
          }
        >
          <CopyButton text={text} />
        </div>
      </div>
    </Bubble>
  );
}
