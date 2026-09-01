/**
 * The confirmation every irreversible or expensive action goes through.
 *
 * CONTRACT.md section 10 bans window.confirm outright and CONTRACT_MOBILE_ADMIN
 * section 9 requires an AlertDialog in front of anything destructive or anything
 * that spends money. This wraps that pattern once so no screen reinvents it.
 *
 * It is deliberately controlled rather than trigger driven. Two of its callers
 * open it from inside a dropdown menu, and Radix unmounts the menu on select,
 * which takes a nested trigger with it; owning the open state in the screen
 * sidesteps that entirely and also lets one dialog serve a whole table.
 *
 * AlertDialogAction already carries the button styling, so the confirm control
 * is that element with a variant class rather than a Button nested inside it,
 * which would put a button inside a button.
 */

import type { ReactNode } from 'react';

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '../../components/ui/alert-dialog';
import { buttonVariants } from '../../components/ui/button';

export interface ConfirmActionProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  /** Paints the confirm control in the destructive colour. */
  destructive?: boolean;
  onConfirm: () => void;
}

export function ConfirmAction({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  cancelLabel = 'Cancel',
  destructive = false,
  onConfirm,
}: ConfirmActionProps): JSX.Element {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {/*
            asChild swaps the default paragraph for a div, because a cost
            estimate or a story headline inside the description is block
            content and a p may not contain a div.
          */}
          <AlertDialogDescription asChild>
            <div>{description}</div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{cancelLabel}</AlertDialogCancel>
          <AlertDialogAction
            className={destructive ? buttonVariants({ variant: 'destructive' }) : undefined}
            onClick={onConfirm}
          >
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
