import { memo, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import CodeBlock from 'src/components/CodeBlock';

interface Props {
  text: string;
}

/** react-markdown types a node's children as `ReactNode`. For a code node it is
 *  the raw source, but it can arrive split across several string children, so
 *  neither `String(children)` nor a cast is safe. */
function codeText(node: ReactNode): string {
  if (typeof node === 'string') return node;
  if (typeof node === 'number') return String(node);
  if (Array.isArray(node)) return (node as ReactNode[]).map((child) => codeText(child)).join('');
  return '';
}

/**
 * Model output, rendered as the markdown it already is.
 *
 * Two things make this safe to point at text a model produced. `react-markdown`
 * builds React elements rather than setting `innerHTML`, and raw HTML in the
 * source is NOT enabled — there is no `rehype-raw` here, deliberately. Adding
 * one turns every answer into an injection surface.
 *
 * Every element is styled explicitly rather than through a typography plugin,
 * because "Tailwind utilities only" is a rule in AGENTS.md and a plugin is a
 * second opinion about what a heading looks like.
 *
 * `memo` is load-bearing during streaming: `StreamingMarkdown` re-renders every
 * animation frame, and without it the whole tree would be re-parsed sixty times
 * a second. The `text` it passes only changes at block boundaries.
 */
function Markdown({ text }: Props) {
  return (
    <ReactMarkdown
      components={{
        a: ({ children, href }) => (
          <a
            className={'text-accent underline underline-offset-2'}
            href={href}
            rel={'noreferrer'}
            target={'_blank'}
          >
            {children}
          </a>
        ),
        blockquote: ({ children }) => (
          <blockquote className={'my-3 border-l-2 border-ink/15 pl-3 text-ink-muted'}>
            {children}
          </blockquote>
        ),
        code: ({ children, className }) => {
          const code = codeText(children).replace(/\n$/, '');
          const language = /language-(\w+)/.exec(className ?? '')?.[1];

          // Block or inline? A fenced block carries a language class or spans
          // more than one line. The remaining case — a single-line fence with
          // no language — renders inline, which is a wash visually.
          if (language !== undefined || code.includes('\n')) {
            return <CodeBlock code={code} language={language} />;
          }

          return (
            <code className={'rounded bg-ink/10 px-1 py-0.5 font-mono text-[0.9em]'}>{code}</code>
          );
        },
        em: ({ children }) => <em className={'italic'}>{children}</em>,
        h1: ({ children }) => (
          <h1 className={'mt-4 mb-2 text-base font-semibold first:mt-0'}>{children}</h1>
        ),
        h2: ({ children }) => (
          <h2 className={'mt-4 mb-2 text-sm font-semibold first:mt-0'}>{children}</h2>
        ),
        h3: ({ children }) => (
          <h3 className={'mt-3 mb-1.5 text-sm font-semibold first:mt-0'}>{children}</h3>
        ),
        hr: () => <hr className={'my-4 border-ink/10'} />,
        li: ({ children }) => <li className={'my-0.5'}>{children}</li>,
        ol: ({ children }) => <ol className={'my-2 list-decimal space-y-0.5 pl-5'}>{children}</ol>,
        p: ({ children }) => (
          <p className={'my-2 leading-relaxed first:mt-0 last:mb-0'}>{children}</p>
        ),
        // CodeBlock brings its own frame, so `pre` is a passthrough rather than
        // a second box around it.
        pre: ({ children }) => <>{children}</>,
        strong: ({ children }) => <strong className={'font-semibold'}>{children}</strong>,
        table: ({ children }) => (
          <div className={'my-3 overflow-x-auto'}>
            <table className={'w-full border-collapse text-xs'}>{children}</table>
          </div>
        ),
        td: ({ children }) => <td className={'border border-ink/10 px-2 py-1'}>{children}</td>,
        th: ({ children }) => (
          <th className={'border border-ink/10 bg-ink/5 px-2 py-1 text-left font-semibold'}>
            {children}
          </th>
        ),
        ul: ({ children }) => <ul className={'my-2 list-disc space-y-0.5 pl-5'}>{children}</ul>,
      }}
      remarkPlugins={[remarkGfm]}
    >
      {text}
    </ReactMarkdown>
  );
}

export default memo(Markdown);
