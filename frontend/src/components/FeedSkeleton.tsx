/**
 * Loading placeholders for the feed, contract section 11: skeleton cards on
 * first paint, never a bare spinner.
 *
 * The whole block is decorative and hidden from assistive technology. The
 * screen that renders it owns the aria-live announcement.
 */

const BAR = 'block rounded bg-muted';

/**
 * The lead image placeholder, contract section 14.5. Its dimensions match
 * CardImage exactly (16 by 9 in full mode, a 72 px square in compact) so the
 * skeleton is the same height as the card that replaces it and the swap costs
 * no layout shift. It carries its own radius rather than reusing Bar, so the
 * class it needs cannot collide with the one Bar already sets.
 */
const IMAGE_FULL = 'block aspect-video w-full shrink-0 rounded-lg bg-muted';
const IMAGE_COMPACT = 'block h-[72px] w-[72px] shrink-0 rounded-md bg-muted';

function Bar({ className }: { className: string }): JSX.Element {
  return <span className={`${BAR} ${className}`} />;
}

export interface FeedSkeletonProps {
  /** Number of placeholder cards. Default 3. */
  count?: number;
  /** Compact list layout, matching NewsCard in compact mode. */
  compact?: boolean;
}

export function FeedSkeleton({ count = 3, compact = false }: FeedSkeletonProps): JSX.Element {
  const cards = Array.from({ length: Math.max(1, count) }, (_, index) => index);

  if (compact) {
    return (
      <div aria-hidden="true" className="flex w-full flex-col gap-3">
        {cards.map((index) => (
          <div
            key={index}
            className="animate-pulse rounded-xl border border-border bg-card px-4 py-4"
          >
            <div className="flex items-start gap-3">
              <span className={IMAGE_COMPACT} />
              <div className="flex min-w-0 flex-1 flex-col">
                <Bar className="h-5 w-4/5" />
                <Bar className="mt-2 h-5 w-3/5" />
                <Bar className="mt-3 h-3 w-full" />
                <Bar className="mt-2 h-3 w-11/12" />
              </div>
            </div>
            <div className="mt-4 flex gap-2">
              <Bar className="h-6 w-16 rounded-full" />
              <Bar className="h-6 w-20 rounded-full" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div
      aria-hidden="true"
      className="mx-auto flex h-full w-full max-w-[480px] flex-col overflow-hidden"
    >
      {cards.map((index) => (
        <div
          key={index}
          className="flex min-h-full flex-none animate-pulse flex-col gap-4 border-b border-border bg-card px-5 py-6 md:border-x"
        >
          <Bar className="h-5 w-24" />
          <span className={IMAGE_FULL} />
          <div>
            <Bar className="h-7 w-full" />
            <Bar className="mt-2 h-7 w-10/12" />
          </div>
          <div>
            <Bar className="h-3.5 w-full" />
            <Bar className="mt-2 h-3.5 w-full" />
            <Bar className="mt-2 h-3.5 w-11/12" />
            <Bar className="mt-2 h-3.5 w-8/12" />
          </div>
          <Bar className="h-16 w-full rounded-md" />
          <div className="flex gap-2">
            <Bar className="h-7 w-20 rounded-full" />
            <Bar className="h-7 w-24 rounded-full" />
            <Bar className="h-7 w-16 rounded-full" />
          </div>
          <Bar className="h-6 w-40 rounded-full" />
          <div className="mt-auto flex items-center justify-between border-t border-border pt-4">
            <Bar className="h-6 w-28" />
            <Bar className="h-6 w-6 rounded-md" />
          </div>
        </div>
      ))}
    </div>
  );
}
