/**
 * The shared empty state, contract section 11. Used when a screen has nothing
 * to render for a legitimate reason: an empty database, no search query yet, no
 * results, or no saved stories.
 */

export interface EmptyStateProps {
  title: string;
  body: string;
  action?: { label: string; onClick: () => void };
}

export function EmptyState({ title, body, action }: EmptyStateProps): JSX.Element {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      <h2 className="font-headline text-xl font-semibold text-fg">{title}</h2>
      <p className="max-w-sm text-sm leading-relaxed text-muted-fg">{body}</p>
      {action ? (
        <button
          type="button"
          onClick={action.onClick}
          className="mt-3 inline-flex min-h-11 items-center justify-center rounded-lg border border-border bg-card px-4 text-sm font-medium text-fg transition-colors duration-150 hover:bg-muted"
        >
          {action.label}
        </button>
      ) : null}
    </div>
  );
}
