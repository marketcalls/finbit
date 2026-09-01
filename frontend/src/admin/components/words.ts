/**
 * Word counting for the story editor.
 *
 * CONTRACT.md section 6 fixes the summary house style at 50 to 80 words, and an
 * editor rewriting one by hand has no other way to tell whether they are still
 * inside it. The count is advisory: the API does not enforce a length, so this
 * reports rather than blocks.
 */

/** Words in a block of text, counting a run of any whitespace as one break. */
export function wordCount(text: string): number {
  const trimmed = text.trim();
  return trimmed === '' ? 0 : trimmed.split(/\s+/).length;
}

/** "62 words", or "1 word", ready to drop into a hint line. */
export function wordCountLabel(text: string): string {
  const count = wordCount(text);
  return `${count} ${count === 1 ? 'word' : 'words'}`;
}
