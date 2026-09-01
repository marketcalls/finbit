/**
 * shadcn/ui input, new-york style, on the FinBit palette.
 *
 * The control sits on bg-card rather than bg-background so a form still reads
 * as a form when it is placed on a card, which is where every admin form lives.
 * Height is 44 px to satisfy the touch target rule in contract section 10, and
 * the text is 16 px below the md breakpoint so iOS Safari does not zoom on
 * focus.
 */

import type * as React from 'react';

import { cn } from '../../lib/utils';

function Input({ className, type, ...props }: React.ComponentProps<'input'>) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        'flex h-11 w-full min-w-0 rounded-md border border-input bg-card px-3 py-2 text-base text-fg transition-colors duration-150',
        'placeholder:text-muted-fg selection:bg-accent selection:text-on-accent',
        'file:me-3 file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-fg',
        'focus-visible:border-ring',
        'disabled:cursor-not-allowed disabled:opacity-50',
        'aria-invalid:border-destructive',
        'md:text-sm',
        className,
      )}
      {...props}
    />
  );
}

export { Input };
