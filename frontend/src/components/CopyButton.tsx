import useCopyToClipboard from 'src/hooks/useCopyToClipboard';

interface Props {
  /** Positioning from the parent; this component owns only its own look. */
  className?: string;
  text: string;
}

/**
 * Copy `text`, and confirm that it happened.
 *
 * The icon swap is the confirmation. `writeText` resolves silently, so without
 * it there is no way to tell a working button from one that failed on a
 * permissions prompt.
 */
export default function CopyButton({ className = '', text }: Props) {
  const { copied, copy } = useCopyToClipboard();

  return (
    <button
      aria-label={copied ? 'Copied' : 'Copy'}
      className={[
        'rounded-md p-1.5 text-ink-muted transition hover:bg-ink/5 hover:text-ink',
        className,
      ].join(' ')}
      onClick={() => copy(text)}
      type={'button'}
    >
      <svg
        aria-hidden={'true'}
        className={'h-3.5 w-3.5'}
        fill={'none'}
        stroke={'currentColor'}
        strokeLinecap={'round'}
        strokeLinejoin={'round'}
        strokeWidth={2}
        viewBox={'0 0 24 24'}
      >
        {copied ? (
          <polyline points={'20 6 9 17 4 12'} />
        ) : (
          <>
            <rect height={13} rx={2} ry={2} width={13} x={9} y={9} />
            <path d={'M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1'} />
          </>
        )}
      </svg>
    </button>
  );
}
