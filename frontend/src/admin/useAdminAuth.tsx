/**
 * Admin session state: context, provider and hook.
 *
 * The session itself lives in api.ts, which is what actually holds the access
 * token and talks to the API. This file is the React view of it, so a screen
 * never has to know that a refresh token exists.
 *
 * Two things happen here that a plain useState could not do. The provider
 * restores a session on mount, because a page reload throws away the in-memory
 * access token while sessionStorage still holds the refresh token, and it
 * subscribes to the transport so a refresh the API refuses mid-session drops
 * the console back to the login form with an explanation rather than leaving a
 * dead screen behind.
 *
 * Sign in failures never say which field was wrong, contract section 3.8. The
 * server already returns one body for both cases; this file must not undo that
 * by guessing.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import {
  AdminApiError,
  adminApi,
  currentUsername,
  describeAdminError,
  hasStoredSession,
  subscribeToSession,
} from './api';

/** What every admin screen may read about the current session. */
export interface AdminAuth {
  /** The signed in username, or null when nobody is signed in. */
  username: string | null;
  /** True once a session is live and calls may be made. */
  authed: boolean;
  /** True only while the initial session restore is in flight. */
  loading: boolean;
  /** The last sign in or session failure, already written for a human. */
  error: string | null;
  /** Resolves true on success. Never throws: read error for the message. */
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => Promise<void>;
}

const SESSION_ENDED_MESSAGE = 'Your admin session ended. Sign in again to continue.';

const LOCKED_MESSAGE =
  'This account is locked after too many failed attempts. Try again in about 15 minutes.';

const RATE_LIMITED_MESSAGE =
  'Too many sign in attempts from this network. Wait a few minutes and try again.';

/**
 * The sentence shown under the sign in form.
 *
 * A wrong username and a wrong password produce the same copy on purpose: the
 * form must not become an account enumeration oracle.
 */
function describeLoginFailure(error: unknown): string {
  if (error instanceof AdminApiError) {
    if (error.isNetworkError) {
      return describeAdminError(error);
    }
    if (error.isLocked) {
      return error.detail !== '' ? error.detail : LOCKED_MESSAGE;
    }
    if (error.isRateLimited) {
      return RATE_LIMITED_MESSAGE;
    }
    if (error.isUnauthorized) {
      return 'Those sign in details did not match an admin account.';
    }
  }
  return describeAdminError(error);
}

const AdminAuthContext = createContext<AdminAuth | null>(null);

export function AdminAuthProvider({ children }: { children: ReactNode }): JSX.Element {
  const [username, setUsername] = useState<string | null>(() => currentUsername());
  const [loading, setLoading] = useState<boolean>(() => hasStoredSession());
  const [error, setError] = useState<string | null>(null);

  // Remembers what the last emit said, so a drop to null can be told apart
  // from a plain re-render and only a real drop writes the expiry message.
  const lastUsername = useRef<string | null>(currentUsername());

  useEffect(() => {
    return subscribeToSession(() => {
      const next = currentUsername();
      const previous = lastUsername.current;
      lastUsername.current = next;
      setUsername(next);
      if (next === null && previous !== null) {
        setError(SESSION_ENDED_MESSAGE);
      }
    });
  }, []);

  useEffect(() => {
    if (!hasStoredSession()) {
      setLoading(false);
      return;
    }

    /*
      StrictMode mounts, unmounts and remounts this in one commit, so restore
      runs twice. That is safe only because api.ts holds the refresh exchange
      as a single in-flight promise: both calls await the same round trip and
      the single-use refresh token is spent once. Do not "simplify" that away,
      or the second call would replay a spent token and the server would revoke
      the session it just issued.
    */
    let live = true;
    adminApi
      .restore()
      .then((name) => {
        if (!live) {
          return;
        }
        lastUsername.current = name;
        setUsername(name);
      })
      .catch(() => {
        // A stale or spent refresh token is the normal reason to land here, and
        // the login form is the answer to it, so it needs no error banner.
        if (live) {
          setUsername(null);
        }
      })
      .finally(() => {
        if (live) {
          setLoading(false);
        }
      });

    return () => {
      live = false;
    };
  }, []);

  const login = useCallback(async (name: string, password: string): Promise<boolean> => {
    setError(null);
    try {
      const signedIn = await adminApi.login(name, password);
      lastUsername.current = signedIn;
      setUsername(signedIn);
      return true;
    } catch (cause) {
      lastUsername.current = null;
      setUsername(null);
      setError(describeLoginFailure(cause));
      return false;
    }
  }, []);

  const logout = useCallback(async (): Promise<void> => {
    await adminApi.logout();
    lastUsername.current = null;
    setUsername(null);
    setError(null);
  }, []);

  const value = useMemo<AdminAuth>(
    () => ({
      username,
      authed: username !== null,
      loading,
      error,
      login,
      logout,
    }),
    [username, loading, error, login, logout],
  );

  return <AdminAuthContext.Provider value={value}>{children}</AdminAuthContext.Provider>;
}

/** Reads the admin session. Throws outside AdminAuthProvider, which is a bug. */
export function useAdminAuth(): AdminAuth {
  const value = useContext(AdminAuthContext);
  if (value === null) {
    throw new Error('useAdminAuth must be used inside AdminAuthProvider.');
  }
  return value;
}
