import type { ReactNode } from 'react';

interface Props {
  /** An action, when there is one worth offering — "Try again". */
  children?: ReactNode;
  detail?: string;
  title: string;
}

/**
 * A page with nothing to show yet, and one sentence on why: nothing
 * selected, nothing saved, not found, could not load. Centred in whatever it
 * fills, which is the whole page beside the sidebar.
 */
export default function EmptyState({ children, detail, title }: Props) {
  return (
    <div
      className={'flex h-full flex-1 flex-col items-center justify-center gap-1 px-6 text-center'}
    >
      <p className={'text-sm text-ink'}>{title}</p>
      {detail && <p className={'max-w-sm text-xs text-ink-muted'}>{detail}</p>}
      {children && <div className={'mt-2'}>{children}</div>}
    </div>
  );
}
