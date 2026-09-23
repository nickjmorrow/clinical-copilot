import { Link } from 'react-router';

interface Props {
  /** True while the thing this starts is what is on screen — a draft has no
   *  row in the list to highlight, so this is what says where you are. */
  isActive: boolean;
  label: string;
  /** Anything to do besides going there. */
  onClick?: () => void;
  to: string;
}

/**
 * The full-width "+ New …" at the top of each sidebar list — conversations,
 * saved questions, definitions. One component so that the three read as the
 * same gesture in three places, which is what they are. A link, because each
 * one goes somewhere: the draft, `/saved/new`, `/definitions/new`.
 */
export default function NewItemLink({ isActive, label, onClick, to }: Props) {
  return (
    <Link
      aria-current={isActive ? 'page' : undefined}
      className={[
        'block w-full rounded-lg border border-ink/10 px-3 py-2 text-center text-xs font-medium text-ink transition',
        isActive ? 'bg-surface-raised' : 'bg-surface hover:bg-surface-raised',
      ].join(' ')}
      onClick={onClick}
      to={to}
    >
      {label}
    </Link>
  );
}
