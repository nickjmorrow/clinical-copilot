interface Props {
  message: string;
  /** Put the message away, for a failure that has nothing to retry. */
  onDismiss?: () => void;
  /** Try the failed request again. Offered whenever there is one to repeat. */
  onRetry?: () => void;
}

/**
 * A failure inside something small — a sidebar list, a card, a panel — where
 * `EmptyState` would take over more than failed.
 *
 * It says what went wrong and offers the way out, because "Could not load"
 * with no retry leaves reloading the whole page as the only option, and the
 * failures worth showing are mostly ones a second attempt fixes.
 */
export default function InlineError({ message, onDismiss, onRetry }: Props) {
  return (
    <div
      className={
        'flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded-lg bg-danger/10 px-2.5 py-2 text-xs text-danger'
      }
      role={'alert'}
    >
      <span className={'min-w-0 flex-1'}>{message}</span>
      {onRetry && (
        <button
          className={'font-medium underline underline-offset-2'}
          onClick={onRetry}
          type={'button'}
        >
          Try again
        </button>
      )}
      {onDismiss && (
        <button
          aria-label={'Dismiss'}
          className={'font-medium opacity-70 hover:opacity-100'}
          onClick={onDismiss}
          type={'button'}
        >
          ✕
        </button>
      )}
    </div>
  );
}
