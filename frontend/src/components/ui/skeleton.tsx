/**
 * shadcn/ui skeleton, on the FinBit palette.
 *
 * Loading placeholders use the muted surface and a pulse, matching the public
 * feed skeleton, so an admin screen never shows a bare spinner on first paint.
 * The pulse is neutralised by the prefers-reduced-motion block in index.css.
 */

import type * as React from 'react';

import { cn } from '../../lib/utils';

function Skeleton({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden="true"
      className={cn('animate-pulse rounded-md bg-muted', className)}
      {...props}
    />
  );
}

export { Skeleton };
