import Caret from 'src/components/Caret';
import useRevealedText from 'src/hooks/useRevealedText';

interface Props {
  text: string;
}

/**
 * Plain text that is still arriving, revealed at a steady pace.
 *
 * The pacing itself is `useRevealedText`, and the reason it is a hook rather
 * than code in here is that there are two streamed surfaces with nothing else
 * in common: this one, which is literal text, and `StreamingMarkdown`, which
 * parses what it has so far. Both need tokens revealed evenly; neither wants
 * the other's rendering.
 *
 * This stays its own leaf component so the per-frame renders happen here rather
 * than in whatever list is drawing it.
 */
export default function StreamingText({ text }: Props) {
  const shown = useRevealedText(text);

  return (
    <>
      {shown}
      <Caret />
    </>
  );
}
