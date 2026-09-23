import Caret from 'src/components/Caret';
import LazyMarkdown from 'src/components/LazyMarkdown';
import useRevealedText from 'src/hooks/useRevealedText';
import { splitStreamingMarkdown } from 'src/markdown';

interface Props {
  text: string;
}

/**
 * An answer that is still arriving, rendered as markdown without flickering.
 *
 * Two problems solved in one place. `useRevealedText` separates the reveal rate
 * from the arrival rate so the text does not land in lumps; `splitStreamingMarkdown`
 * keeps the parser away from the block currently being written, so a half-typed
 * code fence does not render as a paragraph of backticks and then jump.
 *
 * The trailing paragraph is always rendered even when empty, because it is
 * where the caret lives.
 */
export default function StreamingMarkdown({ text }: Props) {
  const shown = useRevealedText(text);
  const { stable, tail } = splitStreamingMarkdown(shown);

  return (
    <>
      {stable && <LazyMarkdown text={stable} />}
      <p className={'my-2 leading-relaxed whitespace-pre-wrap first:mt-0 last:mb-0'}>
        {tail}
        <Caret />
      </p>
    </>
  );
}
