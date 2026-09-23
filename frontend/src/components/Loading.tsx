/**
 * Something is on its way. Used wherever a page used to render nothing, or
 * only its heading, while its data loaded — which reads as "empty" rather
 * than "not yet".
 *
 * It fades in after a short delay (`animate-appear`, in `index.css`), so a
 * load that finishes quickly shows nothing at all instead of flashing a word.
 */
export default function Loading() {
  return (
    <div
      className={
        'flex flex-1 animate-appear items-center justify-center p-6 text-xs text-ink-muted'
      }
      role={'status'}
    >
      Loading…
    </div>
  );
}
