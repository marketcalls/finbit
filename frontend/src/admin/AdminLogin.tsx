/**
 * The admin sign in form, contract section 3.8 and section 9.
 *
 * One deliberate constraint runs through this file: the failure message never
 * says which field was wrong. The API already answers a wrong username and a
 * wrong password identically, and the form must not undo that by, for example,
 * marking only the password field as invalid. Both fields are marked, or
 * neither. The one failure that does get its own copy is the lockout, because
 * telling someone to wait is useful and, by the time it fires, the account is
 * already known to exist.
 *
 * There is no "create an account" path here on purpose. The first admin is made
 * by the CLI (`uv run python -m app.admin_cli create-admin`), so a registration
 * link would be an invitation to an endpoint that does not exist.
 */

import { useState } from 'react';
import type { FormEvent } from 'react';
import { LoaderCircle } from 'lucide-react';

import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { useAdminAuth } from './useAdminAuth';

export function AdminLogin(): JSX.Element {
  const { login, error } = useAdminAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const canSubmit = username.trim() !== '' && password !== '' && !submitting;

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }
    setSubmitting(true);
    const ok = await login(username.trim(), password);
    if (!ok) {
      // A failed attempt keeps the username so a typo in the password is one
      // field to redo, and drops the password so it is never left on screen.
      setPassword('');
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-bg px-4 py-10 text-fg">
      <div className="w-full max-w-sm">
        <h1 className="font-headline text-2xl font-semibold">FinBit admin</h1>
        <p className="mt-1 text-sm text-muted-fg">
          Sign in to control the pipeline, the published stories and the feature flags.
        </p>

        <form
          className="mt-6 flex flex-col gap-4 rounded-xl border border-border bg-card p-6"
          onSubmit={(event) => {
            void handleSubmit(event);
          }}
        >
          <div className="flex flex-col gap-2">
            <Label htmlFor="admin-username">Username</Label>
            <Input
              id="admin-username"
              name="username"
              type="text"
              autoComplete="username"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              required
              disabled={submitting}
              aria-invalid={error !== null}
              value={username}
              onChange={(event) => {
                setUsername(event.target.value);
              }}
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="admin-password">Password</Label>
            <Input
              id="admin-password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              disabled={submitting}
              aria-invalid={error !== null}
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
              }}
            />
          </div>

          {error !== null ? (
            <p role="alert" className="text-sm text-bear">
              {error}
            </p>
          ) : null}

          <Button type="submit" disabled={!canSubmit}>
            {submitting ? (
              <>
                <LoaderCircle aria-hidden="true" className="animate-spin" />
                Signing in
              </>
            ) : (
              'Sign in'
            )}
          </Button>
        </form>

        <p className="mt-4 text-xs text-muted-fg">
          Admin accounts are created from the command line on the server. There is no self
          registration.
        </p>
      </div>
    </div>
  );
}
