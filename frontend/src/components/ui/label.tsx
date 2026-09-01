/**
 * shadcn/ui label, new-york style, on the FinBit palette.
 *
 * Radix supplies the label so that clicking it moves focus into the control
 * even when the control is a custom widget such as Switch or Checkbox, which a
 * plain htmlFor cannot reach. The group-data-[disabled] rules dim the label
 * along with a disabled field group without the caller repeating the state.
 */

import * as LabelPrimitive from '@radix-ui/react-label';
import type * as React from 'react';

import { cn } from '../../lib/utils';

function Label({ className, ...props }: React.ComponentProps<typeof LabelPrimitive.Root>) {
  return (
    <LabelPrimitive.Root
      data-slot="label"
      className={cn(
        'flex select-none items-center gap-2 text-sm font-medium leading-none text-fg',
        'group-data-[disabled=true]:pointer-events-none group-data-[disabled=true]:opacity-50',
        'peer-disabled:cursor-not-allowed peer-disabled:opacity-50',
        className,
      )}
      {...props}
    />
  );
}

export { Label };
