/**
 * shadcn/ui badge, new-york style, on the FinBit palette.
 *
 * Beyond the four stock variants this adds bull, bear and flat, because the
 * admin screens label sentiment and impact direction the same way the public
 * feed does and contract section 10 fixes those three semantics. A badge is a
 * label, not a control: pass asChild when it needs to be a link.
 */

import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import type * as React from 'react';

import { cn } from '../../lib/utils';

const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium transition-colors duration-150 [&>svg]:pointer-events-none [&>svg:not([class*='size-'])]:size-3",
  {
    variants: {
      variant: {
        default: 'border-transparent bg-primary text-primary-foreground',
        secondary: 'border-transparent bg-secondary text-secondary-foreground',
        destructive: 'border-transparent bg-destructive text-destructive-foreground',
        outline: 'border-border text-fg',
        bull: 'border-bull/30 bg-bull/10 text-bull',
        bear: 'border-bear/30 bg-bear/10 text-bear',
        flat: 'border-flat/30 bg-flat/10 text-flat',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
);

export interface BadgeProps
  extends React.ComponentProps<'span'>,
    VariantProps<typeof badgeVariants> {
  /** Render the child element instead of a span, for a badge that is a link. */
  asChild?: boolean;
}

function Badge({ className, variant, asChild = false, ...props }: BadgeProps) {
  const Comp = asChild ? Slot : 'span';

  return (
    <Comp data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
