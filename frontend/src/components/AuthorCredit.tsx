interface Props {
  className?: string;
}

const LINKS = [
  { href: 'https://nickjmorrow.com', label: 'Portfolio' },
  { href: 'https://github.com/nickjmorrow', label: 'GitHub' },
  { href: 'https://github.com/nickjmorrow/clinical-copilot', label: 'Source' },
];

/**
 * Who built this, and where the code is.
 *
 * Shown on the empty chat, which is where a visitor arrives, and in the
 * sidebar footer, which is on every page. The links open a new tab so the
 * demo is still there when you come back to it.
 */
export default function AuthorCredit({ className = '' }: Props) {
  return (
    <p className={['text-xs leading-5 text-ink-muted', className].join(' ')}>
      Built by Nicholas Morrow
      {LINKS.map((link) => (
        <span key={link.href}>
          <span aria-hidden={'true'}> · </span>
          <a
            className={'underline decoration-ink/20 underline-offset-2 transition hover:text-ink'}
            href={link.href}
            rel={'noreferrer'}
            target={'_blank'}
          >
            {link.label}
          </a>
        </span>
      ))}
    </p>
  );
}
