/**
 * The three states every admin screen has to render: loading, empty and failed.
 *
 * They live together because they are the same idea in three moods and because
 * a screen that imports one almost always imports another. Contract section 9
 * asks for a skeleton and an error state on every screen, and CONTRACT.md
 * section 10 forbids a bare spinner on first paint, so the loading blocks are
 * shaped like the content they stand in for rather than being a generic dot.
 *
 * The error block announces itself. An admin who clicked Save and then looked
 * away needs the failure to reach a screen reader without a second click.
 */

import { TriangleAlert } from 'lucide-react';
import type { ReactNode } from 'react';

import { Button } from '../../components/ui/button';
import { Skeleton } from '../../components/ui/skeleton';
import { cn } from '../../lib/utils';

export interface ErrorBlockProps {
  message: string;
  onRetry?: () => void;
  title?: string;
  retryLabel?: string;
  className?: string;
}

/** A failure with a way out of it. */
export function ErrorBlock({
  message,
  onRetry,
  title = 'Something went wrong',
  retryLabel = 'Try again',
  className,
}: ErrorBlockProps): JSX.Element {
  return (
    <div
      role="alert"
      aria-live="polite"
      className={cn(
        'flex flex-col items-start gap-3 rounded-xl border border-border bg-card p-6',
        className,
      )}
    >
      <div className="flex items-center gap-2 text-bear">
        <TriangleAlert aria-hidden="true" className="size-5" />
        <h3 className="text-base font-semibold">{title}</h3>
      </div>
      <p className="text-sm text-muted-fg">{message}</p>
      {onRetry ? (
        <Button type="button" variant="outline" size="sm" onClick={onRetry}>
          {retryLabel}
        </Button>
      ) : null}
    </div>
  );
}

export interface EmptyBlockProps {
  title: string;
  body: string;
  action?: { label: string; onClick: () => void };
  className?: string;
}

/** Nothing to show, said in a way that does not read like a bug. */
export function EmptyBlock({ title, body, action, className }: EmptyBlockProps): JSX.Element {
  return (
    <div
      className={cn(
        'flex flex-col items-start gap-3 rounded-xl border border-border bg-card p-6',
        className,
      )}
    >
      <h3 className="text-base font-semibold text-fg">{title}</h3>
      <p className="text-sm text-muted-fg">{body}</p>
      {action ? (
        <Button type="button" variant="outline" size="sm" onClick={action.onClick}>
          {action.label}
        </Button>
      ) : null}
    </div>
  );
}

/**
 * A card-shaped placeholder.
 *
 * aria-hidden because the bars carry no information; the surrounding screen
 * owns the polite "Loading" announcement so it is made once, not per card.
 */
export function CardSkeleton({ lines = 3 }: { lines?: number }): JSX.Element {
  return (
    <div aria-hidden="true" className="rounded-xl border border-border bg-card p-6">
      <Skeleton className="h-4 w-32" />
      <div className="mt-4 flex flex-col gap-3">
        {Array.from({ length: lines }, (_unused, index) => (
          <Skeleton key={index} className={index === lines - 1 ? 'h-4 w-2/3' : 'h-4 w-full'} />
        ))}
      </div>
    </div>
  );
}

/** Placeholder rows for the content table, matching its column count. */
export function TableSkeleton({
  rows = 6,
  columns = 5,
}: {
  rows?: number;
  columns?: number;
}): JSX.Element {
  return (
    <div aria-hidden="true" className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4">
      {Array.from({ length: rows }, (_unused, row) => (
        <div key={row} className="flex items-center gap-4">
          {Array.from({ length: columns }, (_ignored, column) => (
            <Skeleton key={column} className={column === 0 ? 'h-4 flex-1' : 'h-4 w-16'} />
          ))}
        </div>
      ))}
    </div>
  );
}

/**
 * The polite live region a screen uses while it is fetching.
 *
 * Rendered as visually hidden text rather than as a visible label, because the
 * skeleton is already the visible signal and two of them is noise.
 */
export function LoadingAnnouncement({ children }: { children: ReactNode }): JSX.Element {
  return (
    <p aria-live="polite" className="sr-only">
      {children}
    </p>
  );
}
