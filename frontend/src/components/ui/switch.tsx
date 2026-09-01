/**
 * shadcn/ui switch, on the FinBit palette.
 *
 * The thumb changes colour with the state rather than staying white, because a
 * white thumb on the light theme's #f1f5f9 unchecked track is close to
 * invisible. Unchecked is muted-fg on the muted surface, checked is on-accent on
 * the accent blue, which both clear 4.5:1 in either theme.
 *
 * The control itself is 44 px wide but only 24 px tall, which is the usual
 * switch proportion. Always pair it with a Label so the combined hit area
 * clears the 44 px minimum from contract section 10.
 */

import * as SwitchPrimitive from '@radix-ui/react-switch';
import type * as React from 'react';

import { cn } from '../../lib/utils';

function Switch({ className, ...props }: React.ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        'peer inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors duration-150',
        'data-[state=unchecked]:border-border data-[state=unchecked]:bg-muted',
        'data-[state=checked]:border-primary data-[state=checked]:bg-primary',
        'disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className={cn(
          'pointer-events-none block size-5 rounded-full transition-transform duration-150',
          'data-[state=unchecked]:translate-x-0.5 data-[state=unchecked]:bg-muted-fg',
          'data-[state=checked]:translate-x-[1.375rem] data-[state=checked]:bg-on-accent',
        )}
      />
    </SwitchPrimitive.Root>
  );
}

export { Switch };
