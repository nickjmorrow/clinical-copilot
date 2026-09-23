import { useCallback, useEffect, useState } from 'react';

/** How long the button admits it worked before going back to normal. */
const FEEDBACK_MS = 1500;

export interface Clipboard {
  copied: boolean;
  copy: (text: string) => void;
}

/**
 * Copy, and say so for a moment.
 *
 * The confirmation is the entire point: `navigator.clipboard.writeText`
 * succeeds silently, so without a visible change the user cannot tell a working
 * button from a broken one. A failure — no permission, no secure context —
 * leaves `copied` false, so the button simply does not confirm.
 */
export default function useCopyToClipboard(): Clipboard {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), FEEDBACK_MS);
    return () => clearTimeout(timer);
  }, [copied]);

  const copy = useCallback((text: string) => {
    void navigator.clipboard
      .writeText(text)
      .then(() => setCopied(true))
      // No permission, or not a secure context. The button simply does not
      // confirm, which is the honest outcome.
      .catch(() => setCopied(false));
  }, []);

  return { copied, copy };
}
