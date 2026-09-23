import type { ReactNode } from 'react';

interface Props {
  /** Controls that belong beside the title — a page's own buttons. */
  actions?: ReactNode;
  children: ReactNode;
  /** A line or two under the title saying what the page is. */
  description?: ReactNode;
  /** The heading, and anything that belongs directly under it. */
  title: ReactNode;
  /** `form` for fields, `reading` for prose and lists, `table` for data. */
  width?: 'form' | 'reading' | 'table';
}

// Named for what fills the column rather than by size, so a new page picks
// the one that describes it instead of a number that drifts.
const WIDTHS = {
  form: 'max-w-2xl',
  reading: 'max-w-3xl',
  table: 'max-w-4xl',
} as const;

/**
 * Every page that is not the chat: the pane that scrolls, the column centred
 * in it, and a heading.
 *
 * Seven pages used to spell this out themselves, and had drifted to four
 * widths — three of them forms that stretched to the edge of a wide window,
 * which is not a width anyone reads a form at. The pane scrolls rather than
 * the column for the reason CONVENTIONS.md gives for the chat: the scrollbar
 * rides the window's edge, not the text's.
 */
export default function Page({ actions, children, description, title, width = 'reading' }: Props) {
  return (
    <div className={'flex h-full flex-col overflow-y-auto px-4 py-5 sm:px-6'}>
      <div className={['mx-auto flex w-full flex-col gap-4', WIDTHS[width]].join(' ')}>
        <header className={'flex items-start justify-between gap-3'}>
          <div className={'min-w-0'}>
            <h2 className={'text-sm font-semibold tracking-tight text-ink'}>{title}</h2>
            {description && <div className={'mt-1 text-xs text-ink-muted'}>{description}</div>}
          </div>
          {actions}
        </header>
        {children}
      </div>
    </div>
  );
}
