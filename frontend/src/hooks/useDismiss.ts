import { type RefObject, useEffect } from 'react';

/**
 * Close an open overlay the two ways every overlay must close.
 *
 * Escape and a click elsewhere are not a nicety: a popover you can only close
 * by clicking the button that opened it is a trap on a touchscreen, and one
 * that survives Escape is the reason people reach for the Back button.
 *
 * `pointerdown` rather than `click`. A click fires after the press completes,
 * so a menu item under the cursor can receive the press, re-render, and leave
 * the click landing on whatever took its place. Closing on the press is both
 * earlier and unambiguous.
 *
 * Synchronising with something outside React is what effects are for — see
 * AGENTS.md on when to write one — and the listeners are removed on unmount
 * and whenever `isOpen` goes false, so nothing accumulates.
 */
export default function useDismiss(
  ref: RefObject<HTMLElement | null>,
  isOpen: boolean,
  onDismiss: () => void,
): void {
  useEffect(() => {
    if (!isOpen) return;

    const onPointerDown = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) onDismiss();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onDismiss();
    };

    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [isOpen, onDismiss, ref]);
}
