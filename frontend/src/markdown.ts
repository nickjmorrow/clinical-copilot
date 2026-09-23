/**
 * Splitting markdown that has not finished arriving.
 *
 * Markdown and streaming fight each other, and naively rendering every frame
 * loses twice. It is slow — a parse of the whole message per animation frame —
 * and it flickers: an unclosed ``` renders as a paragraph of literal backticks
 * until the closing fence lands, then snaps into a code block. A half-written
 * table is worse.
 *
 * So the revealed text is cut in two. Everything up to the last *completed*
 * block is `stable` and gets parsed; the block still being typed is `tail` and
 * renders as plain text until it is finished. `stable` changes only at block
 * boundaries, which is what makes memoising the parse worth anything.
 *
 * No React here — it is a function of a string.
 */

const FENCE = /^\s*```/;

export interface StreamingMarkdownSplit {
  /** Complete blocks. Safe to parse, and rarely changes. */
  stable: string;
  /** The block still being written. Rendered as-is. */
  tail: string;
}

export function splitStreamingMarkdown(text: string): StreamingMarkdownSplit {
  const lines = text.split('\n');

  // Index one past the last line that belongs to a finished block.
  let boundary = 0;
  let isInFence = false;
  let fenceOpenedAt: null | number = null;

  for (const [index, line] of lines.entries()) {
    if (FENCE.test(line)) {
      if (isInFence) {
        // A fence CLOSING completes a block, and it is the only boundary a
        // code block gets — no blank line follows one at the end of a message.
        // Without this case a finished code block sits in `tail` as plain text
        // until something else arrives, which for the last block is never.
        isInFence = false;
        fenceOpenedAt = null;
        boundary = index + 1;
      } else {
        isInFence = true;
        fenceOpenedAt = index;
      }
      continue;
    }

    // Blank lines inside a fence are part of the code, not a block boundary.
    //
    // The LAST line is skipped even when empty, and that is the whole trick of
    // streaming: text ending in a single "\n" splits to a final empty element
    // that looks exactly like a blank line but is not one yet. Treating it as a
    // boundary promotes a block that the very next character may continue — a
    // list whose next item has not arrived — and `stable` then has to give it
    // back. A real blank line needs a line after it.
    const isLastLine = index === lines.length - 1;
    if (!isInFence && !isLastLine && line.trim() === '') boundary = index + 1;
  }

  // An unclosed fence caps everything after it, however many blank lines the
  // half-written code contains.
  if (fenceOpenedAt !== null) boundary = Math.min(boundary, fenceOpenedAt);

  // Nothing complete yet: one block, still being written.
  if (boundary <= 0) return { stable: '', tail: text };

  return {
    // Trailing blank lines are separator, not content, and markdown renders
    // the same with or without them. Dropping them keeps `stable` byte-identical
    // across the frame where a new block's first character lands, which is what
    // lets `Markdown` stay memoised instead of re-parsing on every boundary.
    stable: lines.slice(0, boundary).join('\n').replace(/\n+$/, ''),
    tail: lines.slice(boundary).join('\n'),
  };
}
