/**
 * shadcn/ui button, new-york style, rewritten against the FinBit palette.
 *
 * Sizes are deliberately taller than stock shadcn: contract section 10 sets a
 * 44 by 44 px minimum touch target, so the default and icon sizes are h-11 and
 * size-11. The sm size stays at 36 px because it is only used inside the admin
 * data table, where a 44 px control in every row makes the table unreadable and
 * the whole row is already a pointer target.
 *
 * No focus utility is declared here on purpose. index.css sets a 2 px
 * :focus-visible outline on everything focusable in both themes, so adding a
 * ring here would draw a second indicator on top of it.
 */

import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import type * as React from 'react';

import { cn } from '../../lib/utils';

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary/90',
        destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
        outline: 'border border-input bg-card text-fg hover:bg-muted',
        secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
        ghost: 'text-muted-fg hover:bg-muted hover:text-fg',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-11 px-4 py-2 has-[>svg]:px-3',
        sm: 'h-9 gap-1.5 rounded-md px-3 text-sm has-[>svg]:px-2.5',
        lg: 'h-12 rounded-md px-6 text-base has-[>svg]:px-4',
        icon: 'size-11',
        'icon-sm': 'size-9',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
);

export interface ButtonProps
  extends React.ComponentProps<'button'>,
    VariantProps<typeof buttonVariants> {
  /** Render the child element instead of a button, for links styled as buttons. */
  asChild?: boolean;
}

function Button({ className, variant, size, asChild = false, ...props }: ButtonProps) {
  const Comp = asChild ? Slot : 'button';

  return (
    <Comp
      data-slot="button"
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}

export { Button, buttonVariants };
