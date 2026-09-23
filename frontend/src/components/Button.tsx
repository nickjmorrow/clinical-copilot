import type { ButtonHTMLAttributes, ReactNode } from 'react';

type Size = 'md' | 'sm';
type Variant = 'primary' | 'secondary';

interface Props extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'type'> {
  children: ReactNode;
  /** The confirm-then-destroy tint — a delete button reads as an ordinary
   *  secondary action until pressed once, then switches to this to ask for
   *  the second click. Never paired with `variant="primary"` anywhere in
   *  this app; the type doesn't forbid it because a future one-shot danger
   *  action is a reasonable thing to want, but nothing here does that yet. */
  danger?: boolean;
  size?: Size;
  /** `button` unless it submits a form. Never `reset`: nothing here wants
   *  a control that silently empties what somebody typed. */
  type?: 'button' | 'submit';
  variant?: Variant;
}

const SIZE: Record<Size, string> = {
  md: 'px-3 py-1.5 text-xs',
  sm: 'px-2.5 py-1 text-xs',
};

/**
 * The two button identities this app actually has, named once.
 *
 * Every secondary/ghost button — toolbar actions, form actions, the header
 * nav — was the same handful of Tailwind utilities copy-pasted with small,
 * unintentional drift: `ICON_BUTTON` defined identically in both
 * `PredicateEditor.tsx` and `AgeBandListInput.tsx` (one commented "first
 * found live" in the other, and neither was ever consolidated), `BUTTON`/
 * `PRIMARY_BUTTON` local to `DefinitionForm.tsx`, and an unnamed duplicate
 * in half a dozen other files — `disabled:opacity-30` in two places where
 * everywhere else had settled on `-40`, `px-2` where everywhere else had
 * `px-2.5`. Nothing about those differences meant anything; they were just
 * copies nobody had a reason to keep in sync. One component is the reason
 * they can't drift again.
 *
 * `size="sm"` is the compact toolbar/inline-row weight; `size="md"` is the
 * heavier form-action weight. `font-medium` tracks `variant="primary"` or
 * `size="md"` — every primary button in this app is bold regardless of
 * size, and `DefinitionForm.tsx`'s form-action row is the one place a
 * secondary button is too, which is why weight is not simply a `size`
 * lookup. `variant="primary"` is the one accent-filled treatment used
 * everywhere a call-to-action needs one.
 *
 * A plain text link-style "Cancel" (`AccessPanel.tsx`) and icon-only
 * disclosure triggers (`ToolCard.tsx`'s chevron, `ConversationMenu.tsx`,
 * `ThinkingBlock.tsx`) are deliberately not here — a different visual role
 * each, not a drifted copy of this one.
 */
export default function Button({
  children,
  className = '',
  danger = false,
  size = 'md',
  type = 'button',
  variant = 'secondary',
  ...rest
}: Props) {
  const weight = variant === 'primary' || size === 'md' ? 'font-medium' : '';
  const tone = danger
    ? 'border border-danger/40 text-danger'
    : variant === 'primary'
      ? 'bg-accent text-on-accent hover:opacity-90'
      : size === 'md'
        ? 'border border-ink/10 text-ink hover:border-ink/20'
        : 'border border-ink/10 text-ink-muted hover:border-ink/20 hover:text-ink';

  return (
    <button
      className={['rounded-lg transition disabled:opacity-40', SIZE[size], weight, tone, className]
        .filter(Boolean)
        .join(' ')}
      type={type === 'submit' ? 'submit' : 'button'}
      {...rest}
    >
      {children}
    </button>
  );
}
