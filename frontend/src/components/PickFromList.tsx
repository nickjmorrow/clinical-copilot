import type { ReactNode } from 'react';

interface Props {
  /** What a wide window shows: usually an `EmptyState` saying to pick one. */
  children: ReactNode;
  /** The same list the sidebar shows for this section. */
  list: ReactNode;
}

/**
 * A list page with nothing selected.
 *
 * On a wide window the list is in the sidebar beside the page, so the page
 * says to pick from it. On a phone the sidebar is a drawer, and "pick one"
 * would point at a list that is not on screen — so there the list *is* the
 * page, which is what a phone does with a list and its detail anyway.
 * Choosing an item is a link, so it lands on the detail like it would from
 * the sidebar.
 */
export default function PickFromList({ children, list }: Props) {
  return (
    <>
      <div className={'flex min-h-0 flex-1 flex-col md:hidden'}>{list}</div>
      <div className={'hidden min-h-0 flex-1 flex-col md:flex'}>{children}</div>
    </>
  );
}
