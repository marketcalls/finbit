/**
 * The admin gate: sign in, or create the one admin account this deployment
 * will ever have. Contract section 3.8 and registration contract section 4.
 *
 * Which of the two faces to show is not a guess. GET /api/admin/auth/status
 * answers it on mount, and until it answers this screen shows a skeleton. That
 * matters more than it looks: a registration form flashing for one frame on a
 * deployed instance reads as a hole an attacker could have walked through, even
 * though the API would answer 404 to anyone who tried. Never render a face on a
 * hunch, and never fall back to one when the status call fails; offer a retry
 * instead.
 *
 * Two constraints carried over from phase 2 still hold on the sign in face. The
 * failure message never says which field was wrong, because the API answers a
 * wrong username and a wrong password identically and the form must not undo
 * that by marking one field. And the password is dropped after a failed
 * attempt, so it is never left sitting on screen.
 *
 * The registration face does the opposite with its passwords: it keeps them.
 * The likely reason a registration fails is a mistyped bootstrap token, and
 * making someone retype a twelve character password twice to fix a token typo
 * is a punishment for the wrong mistake.
 */

import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { LoaderCircle } from 'lucide-react';

import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Skeleton } from '../components/ui/skeleton';
import { AdminApiError, adminApi, describeAdminError, isAbortError } from './api';
import {
  PasswordChecklist,
  USERNAME_RULE_HINT,
  passwordRules,
  usernameHasProblem,
} from './components/PasswordChecklist';
import { ErrorBlock } from './components/StateBlocks';
import { useAdminAuth } from './useAdminAuth';

/**
 * 'checking' is the only state that renders neither form. 'unavailable' is what
 * a failed status call gets: the console cannot know which face is correct, so
 * it says so rather than picking one.
 */
type Face = 'checking' | 'register' | 'login' | 'unavailable';

/**
 * Why the status call failed, said in terms of what to do about it.
 *
 * The 404 case is worth naming: it means the API is running but predates the
 * registration routes, which is a deployment that needs updating rather than a
 * network to retry.
 */
function describeStatusFailure(error: unknown): string {
  if (error instanceof AdminApiError) {
    if (error.isNotFound) {
      return 'This API is older than the console and has no admin registration routes. Update the FinBit API, then reload this page.';
    }
    if (error.isRateLimited) {
      return 'Too many requests from this network. Wait a minute, then try again.';
    }
  }
  return describeAdminError(error);
}

export function AdminLogin(): JSX.Element {
  const { notice } = useAdminAuth();
  const [face, setFace] = useState<Face>('checking');
  const [statusError, setStatusError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let live = true;

    adminApi
      .authStatus(controller.signal)
      .then((status) => {
        if (live) {
          setFace(status.registration_open ? 'register' : 'login');
        }
      })
      .catch((cause: unknown) => {
        // StrictMode's second mount aborts the first request. That is not a
        // failure and must not paint an error over a request still in flight.
        if (!live || isAbortError(cause)) {
          return;
        }
        setStatusError(describeStatusFailure(cause));
        setFace('unavailable');
      });

    return () => {
      live = false;
      controller.abort();
    };
  }, [attempt]);

  const heading = face === 'register' ? 'Create the admin account' : 'FinBit admin';

  return (
    <div className="flex min-h-dvh items-center justify-center bg-bg px-4 py-10 text-fg">
      <div className="w-full max-w-sm">
        <h1 className="font-headline text-2xl font-semibold">{heading}</h1>

        {face === 'login' ? (
          <p className="mt-1 text-sm text-muted-fg">
            Sign in to control the pipeline, the published stories and the feature flags.
          </p>
        ) : null}

        {face === 'register' ? (
          <p className="mt-1 text-sm text-muted-fg">
            This instance has no admin yet. Set one up to reach the console.
          </p>
        ) : null}

        {notice !== null ? (
          <p
            role="status"
            className="mt-4 rounded-md border border-border bg-muted px-3 py-2 text-sm text-fg"
          >
            {notice}
          </p>
        ) : null}

        {face === 'checking' ? <GateSkeleton /> : null}

        {face === 'login' ? <SignInForm /> : null}

        {face === 'register' ? (
          <RegisterForm
            onClosed={() => {
              setFace('login');
            }}
          />
        ) : null}

        {face === 'unavailable' ? (
          <ErrorBlock
            className="mt-6"
            title="Could not reach the API"
            message={
              statusError ??
              'The admin console needs the FinBit API to tell it whether an account exists yet.'
            }
            retryLabel="Try again"
            onRetry={() => {
              setStatusError(null);
              setFace('checking');
              setAttempt((value) => value + 1);
            }}
          />
        ) : null}
      </div>
    </div>
  );
}

/**
 * The placeholder shown while the status call is in flight.
 *
 * Shaped like a form so the layout does not jump when the real one arrives, and
 * deliberately shaped like neither form in particular.
 */
function GateSkeleton(): JSX.Element {
  return (
    <>
      <div
        aria-hidden="true"
        className="mt-6 flex flex-col gap-4 rounded-xl border border-border bg-card p-6"
      >
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-11 w-full" />
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-11 w-full" />
        <Skeleton className="h-11 w-full" />
      </div>
      <p aria-live="polite" className="sr-only">
        Checking whether this FinBit instance has an admin account yet.
      </p>
    </>
  );
}

/** The phase 2 sign in form, unchanged in behaviour. */
function SignInForm(): JSX.Element {
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
    <>
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
        This deployment has one admin account. A forgotten password is reset on the server with
        <code className="mx-1 font-mono">uv run python -m app.admin_cli reset-password</code>.
      </p>
    </>
  );
}

/**
 * The one-time registration form.
 *
 * Nothing here blocks a submit except two empty fields and two passwords that
 * do not match, which is the one check the server cannot make. Every other rule
 * is shown and left to the API, so a mirrored rule that is wrong can never stop
 * an operator claiming their own instance.
 */
function RegisterForm({ onClosed }: { onClosed: () => void }): JSX.Element {
  const { register, error } = useAdminAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [token, setToken] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const rules = passwordRules(password, username);
  const mismatched = confirm !== '' && confirm !== password;
  const malformedUsername = usernameHasProblem(username.trim());

  const canSubmit =
    username.trim() !== '' &&
    password !== '' &&
    confirm !== '' &&
    token.trim() !== '' &&
    !mismatched &&
    !submitting;

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }
    setSubmitting(true);
    const outcome = await register(username.trim(), password, token.trim());
    if (outcome === 'created') {
      // A live session now exists, so this whole screen is about to be replaced
      // by the dashboard. Touching state here would only fight that.
      return;
    }
    if (outcome === 'closed') {
      onClosed();
      return;
    }
    setSubmitting(false);
  }

  return (
    <>
      <form
        className="mt-6 flex flex-col gap-4 rounded-xl border border-border bg-card p-6"
        onSubmit={(event) => {
          void handleSubmit(event);
        }}
      >
        <div className="flex flex-col gap-2">
          <Label htmlFor="register-username">Username</Label>
          <Input
            id="register-username"
            name="username"
            type="text"
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            required
            disabled={submitting}
            aria-invalid={malformedUsername}
            aria-describedby="register-username-hint"
            value={username}
            onChange={(event) => {
              setUsername(event.target.value);
            }}
          />
          <p
            id="register-username-hint"
            className={malformedUsername ? 'text-xs text-bear' : 'text-xs text-muted-fg'}
          >
            {USERNAME_RULE_HINT}
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor="register-password">Password</Label>
          <Input
            id="register-password"
            name="new-password"
            type="password"
            autoComplete="new-password"
            required
            disabled={submitting}
            aria-describedby="register-password-rules"
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
            }}
          />
          <PasswordChecklist id="register-password-rules" rules={rules} className="mt-1" />
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor="register-confirm">Confirm password</Label>
          <Input
            id="register-confirm"
            name="confirm-password"
            type="password"
            autoComplete="new-password"
            required
            disabled={submitting}
            aria-invalid={mismatched}
            aria-describedby={mismatched ? 'register-confirm-error' : undefined}
            value={confirm}
            onChange={(event) => {
              setConfirm(event.target.value);
            }}
          />
          {mismatched ? (
            <p id="register-confirm-error" className="text-xs text-bear">
              The two passwords do not match yet.
            </p>
          ) : null}
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor="register-token">Bootstrap token</Label>
          <Input
            id="register-token"
            name="bootstrap-token"
            type="text"
            autoComplete="off"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            required
            disabled={submitting}
            className="font-mono"
            placeholder="7Kq2-9fPx-Lm4w-Rt8v"
            aria-describedby="register-token-hint"
            value={token}
            onChange={(event) => {
              setToken(event.target.value);
            }}
          />
          <p id="register-token-hint" className="text-xs text-muted-fg">
            Printed in the API server console when it started.
          </p>
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
              Creating the account
            </>
          ) : (
            'Create admin account'
          )}
        </Button>
      </form>

      <p className="mt-4 text-xs text-muted-fg">
        This is a one-time setup. FinBit has exactly one admin account for the life of the
        deployment, so no further accounts can be created after this one. Everyone who needs the
        console shares it, and a forgotten password is reset on the server with the admin CLI.
      </p>
    </>
  );
}
