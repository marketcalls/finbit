/**
 * Change the admin password, registration contract sections 3.3 and 4.
 *
 * Succeeding here ends every admin session, this tab's included, because the
 * API revokes all admin refresh tokens as part of the change. That is the point
 * of the feature: a password is changed when someone should stop having access,
 * and leaving their other browser signed in would defeat it. So this dialog
 * says what will happen before it happens, and the console drops back to the
 * sign in form afterwards with the same fact restated there.
 *
 * The current password field is not a formality either. Without it, anyone who
 * walked up to an unlocked screen could take the one account this deployment
 * has, and there is no second admin to take it back.
 */

import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { LoaderCircle } from 'lucide-react';

import { Button } from '../../components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../components/ui/dialog';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { useAdminAuth } from '../useAdminAuth';
import { PasswordChecklist, passwordRules } from './PasswordChecklist';

export interface ChangePasswordDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ChangePasswordDialog({
  open,
  onOpenChange,
}: ChangePasswordDialogProps): JSX.Element {
  const { username, changePassword } = useAdminAuth();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [failure, setFailure] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Nothing typed here survives a close. A password left in state would come
  // back on the next open, in a field the operator did not expect to be filled.
  useEffect(() => {
    if (!open) {
      setCurrent('');
      setNext('');
      setConfirm('');
      setFailure(null);
      setSubmitting(false);
    }
  }, [open]);

  const rules = passwordRules(next, username ?? '');
  const mismatched = confirm !== '' && confirm !== next;
  const unchanged = next !== '' && next === current;

  const canSubmit =
    current !== '' && next !== '' && confirm !== '' && !mismatched && !unchanged && !submitting;

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }
    setSubmitting(true);
    setFailure(null);
    const message = await changePassword(current, next);
    if (message === null) {
      // The session is already gone, so the console is rendering the sign in
      // form by now. Closing keeps the dialog from being the last thing on
      // screen if this component outlives the change by a frame.
      onOpenChange(false);
      return;
    }
    setFailure(message);
    setSubmitting(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Change password</DialogTitle>
          <DialogDescription>
            Changing it signs out every admin session, including this one and any other browser or
            device. You will sign in again with the new password.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            void handleSubmit(event);
          }}
        >
          {/*
            A hidden username field is what lets a password manager file the new
            password under the right account instead of creating a second entry.
          */}
          <input
            type="text"
            name="username"
            autoComplete="username"
            value={username ?? ''}
            readOnly
            hidden
          />

          <div className="flex flex-col gap-2">
            <Label htmlFor="change-current">Current password</Label>
            <Input
              id="change-current"
              name="current-password"
              type="password"
              autoComplete="current-password"
              required
              disabled={submitting}
              value={current}
              onChange={(event) => {
                setCurrent(event.target.value);
              }}
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="change-next">New password</Label>
            <Input
              id="change-next"
              name="new-password"
              type="password"
              autoComplete="new-password"
              required
              disabled={submitting}
              aria-invalid={unchanged}
              aria-describedby="change-next-rules"
              value={next}
              onChange={(event) => {
                setNext(event.target.value);
              }}
            />
            <PasswordChecklist id="change-next-rules" rules={rules} className="mt-1" />
            {unchanged ? (
              <p className="text-xs text-bear">
                The new password is the same as the current one. Choose a different one.
              </p>
            ) : null}
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="change-confirm">Confirm new password</Label>
            <Input
              id="change-confirm"
              name="confirm-password"
              type="password"
              autoComplete="new-password"
              required
              disabled={submitting}
              aria-invalid={mismatched}
              aria-describedby={mismatched ? 'change-confirm-error' : undefined}
              value={confirm}
              onChange={(event) => {
                setConfirm(event.target.value);
              }}
            />
            {mismatched ? (
              <p id="change-confirm-error" className="text-xs text-bear">
                The two passwords do not match yet.
              </p>
            ) : null}
          </div>

          {failure !== null ? (
            <p role="alert" className="text-sm text-bear">
              {failure}
            </p>
          ) : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={submitting}
              onClick={() => {
                onOpenChange(false);
              }}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              {submitting ? (
                <>
                  <LoaderCircle aria-hidden="true" className="animate-spin" />
                  Changing
                </>
              ) : (
                'Change password and sign out'
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
