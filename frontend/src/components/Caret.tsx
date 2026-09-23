/**
 * The blinking block at the end of text that is still arriving.
 *
 * Gives the eye something to rest on between words, which is most of what makes
 * streaming text feel calm rather than frantic. Decorative, so it is hidden
 * from assistive technology — the transcript's `aria-live` region announces the
 * text itself.
 */
export default function Caret() {
  return (
    <span
      aria-hidden={'true'}
      className={
        'ml-0.5 inline-block h-[1em] w-[2px] translate-y-[0.15em] animate-pulse bg-current align-baseline motion-reduce:animate-none'
      }
    />
  );
}
