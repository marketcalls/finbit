/**
 * The shared inline error, contract section 11. Errors never take over the
 * screen and never use a browser dialog: they render in place with a retry
 * button.
 *
 * The message text sits on the foreground token so it clears 4.5:1 in both
 * themes, while the bear token colours the icon, the border and the tint.
 */

import { IconAlert } from './Icons';

export interface ErrorStateProps {
  message: string;
  onRetry: () => void;
}

export function ErrorState({ message, onRetry }: ErrorStateProps): JSX.Element {
  return (
    <div
      role="alert"
      aria-live="polite"
      className="flex flex-col items-center gap-3 rounded-xl border border-bear/40 bg-bear/10 px-4 py-6 text-center"
    >
      <IconAlert className="h-6 w-6 text-bear" />
      <p className="max-w-sm text-sm leading-relaxed text-fg">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="inline-flex min-h-11 items-center justify-center rounded-lg border border-border bg-card px-4 text-sm font-medium text-fg transition-colors duration-150 hover:bg-muted"
      >
        Try again
      </button>
    </div>
  );
}
