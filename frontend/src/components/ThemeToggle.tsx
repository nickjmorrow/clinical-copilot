import type { ReactNode } from 'react';
import useTheme, { type ThemePreference } from 'src/hooks/useTheme';

/**
 * The three choices, in the order a slider would put them: darkest on the
 * right. `system` sits in the middle because it is the default, not because it
 * is between the other two.
 *
 * These are plain values rather than three little icon components — a
 * component file exports its component and nothing else, and `no-multi-comp`
 * is the rule that enforces it.
 */
const OPTIONS: { icon: ReactNode; label: string; value: ThemePreference }[] = [
  {
    icon: (
      <>
        <circle cx={12} cy={12} r={4} />
        <path
          d={
            'M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41'
          }
        />
      </>
    ),
    label: 'Light',
    value: 'light',
  },
  {
    icon: (
      <>
        <rect height={13} rx={2} width={20} x={2} y={4} />
        <path d={'M8 21h8M12 17v4'} />
      </>
    ),
    label: 'System',
    value: 'system',
  },
  {
    icon: <path d={'M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z'} />,
    label: 'Dark',
    value: 'dark',
  },
];

/**
 * Pick a theme.
 *
 * Three buttons rather than one that cycles, because a cycling control cannot
 * tell you what it will do next or what state you are in — with three themes
 * and one icon, "which one is showing" and "which one did I pick" are the same
 * glyph and you have to click to find out. Here both are visible at once: the
 * pressed segment is the preference, and the page is the result.
 *
 * `aria-pressed` rather than a radio group. The semantics are close enough and
 * a radio group brings a keyboard contract with it — arrow keys move the
 * selection, one tab stop for the set — that would be a bug to half-implement.
 * Three toggle buttons are three tab stops and need no keyboard code at all.
 */
export default function ThemeToggle() {
  const { choose, preference } = useTheme();

  return (
    <div
      aria-label={'Theme'}
      className={'flex items-center gap-0.5 rounded-lg border border-ink/10 p-0.5'}
      role={'group'}
    >
      {OPTIONS.map((option) => {
        const isActive = option.value === preference;
        return (
          <button
            aria-label={option.label}
            aria-pressed={isActive}
            className={[
              'rounded-md p-1.5 transition',
              isActive ? 'bg-surface-raised text-ink' : 'text-ink-muted hover:text-ink',
            ].join(' ')}
            key={option.value}
            onClick={() => {
              choose(option.value);
            }}
            title={option.label}
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
              {option.icon}
            </svg>
          </button>
        );
      })}
    </div>
  );
}
