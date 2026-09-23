import { lazy, Suspense } from 'react';

interface Props {
  text: string;
}

// The markdown renderer is the largest thing the app bundles after React
// itself — about a quarter of the JavaScript — and the landing page has no
// answer to render yet. So it arrives with the first answer instead of with
// the first page.
const Markdown = lazy(() => import('src/components/Markdown'));

/**
 * `Markdown`, loaded on first use. Until it arrives the text is shown as
 * plain paragraphs, so an answer never blanks while its renderer loads — it
 * gains its formatting a moment later instead.
 */
export default function LazyMarkdown({ text }: Props) {
  return (
    <Suspense fallback={<p className={'leading-relaxed whitespace-pre-wrap'}>{text}</p>}>
      <Markdown text={text} />
    </Suspense>
  );
}
