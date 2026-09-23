import CopyButton from 'src/components/CopyButton';

interface Props {
  code: string;
  language?: string;
}

/**
 * A fenced code block from the model, with the one affordance people actually
 * use: copy.
 *
 * Deliberately NOT syntax highlighted. Every highlighter worth having
 * (highlight.js, shiki, prism) is larger than this entire bundle, and the
 * choice of which languages to ship is a product decision rather than a
 * default. The seam is here when you want it: highlight `code` and render the
 * result in place of the plain `<code>` below.
 */
export default function CodeBlock({ code, language }: Props) {
  return (
    <div className={'my-3 overflow-hidden rounded-lg border border-ink/10 bg-surface-raised'}>
      <div className={'flex items-center justify-between border-b border-ink/5 px-3 py-1'}>
        <span className={'font-mono text-[11px] text-ink-muted'}>{language ?? 'text'}</span>
        <CopyButton text={code} />
      </div>

      <pre className={'overflow-x-auto px-3 py-2.5 text-xs leading-relaxed'}>
        <code className={'font-mono'}>{code}</code>
      </pre>
    </div>
  );
}
