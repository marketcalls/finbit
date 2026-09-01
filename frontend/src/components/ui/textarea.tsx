/**
 * shadcn/ui textarea, new-york style, on the FinBit palette.
 *
 * Used by the admin content editor for the summary and why-it-matters fields,
 * which are paragraphs rather than lines, so the default is three rows tall and
 * grows with field-sizing-content where the browser supports it.
 */

import type * as React from 'react';

import { cn } from '../../lib/utils';

function Textarea({ className, ...props }: React.ComponentProps<'textarea'>) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        'flex min-h-20 w-full rounded-md border border-input bg-card px-3 py-2 text-base text-fg transition-colors duration-150 field-sizing-content',
        'placeholder:text-muted-fg selection:bg-accent selection:text-on-accent',
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

export { Textarea };
