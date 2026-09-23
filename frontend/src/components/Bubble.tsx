import type { ReactNode } from 'react';

interface Props {
  children: ReactNode;
  role: 'assistant' | 'user';
}

/**
 * A line of the conversation, from either side.
 *
 * The two sides are deliberately NOT symmetrical, and this is the one file that
 * knows why. A user message is short, literal and typed by hand, so it gets the
 * familiar tinted bubble on the right and keeps its own line breaks. An answer
 * is markdown — headings, lists, tables, fenced code — and a 85%-wide tinted box
 * is actively hostile to all four: a code block inside one wraps at half the
 * width it needs, and every nested background has to be chosen to sit on the
 * bubble rather than on the page. So the model's side is plain full-width text
 * on the page background, which is what every chat client that renders real
 * markdown converged on.
 *
 * Still one component rather than two, so the shared decisions — how far the
 * column runs, how a turn is spaced from the one above it — cannot drift apart.
 * `whitespace-pre-wrap` is on the user side only: `Markdown` emits real block
 * elements and pre-wrap would turn the newlines between them into blank lines.
 */
export default function Bubble({ children, role }: Props) {
  const isUser = role === 'user';

  return (
    <div className={isUser ? 'flex justify-end pl-8' : 'flex justify-start'}>
      <div
        className={
          isUser
            ? 'max-w-[85%] rounded-2xl rounded-br-sm bg-accent px-4 py-2.5 text-sm whitespace-pre-wrap text-on-accent'
            : 'w-full min-w-0 text-sm text-ink'
        }
      >
        {children}
      </div>
    </div>
  );
}
