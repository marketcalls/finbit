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
 *
 * Phase 3 adds two more ways in and out of a session, and with them a second
 * message channel. `error` is a failure the operator has to fix; `notice` is
 * something that simply happened, such as registration closing under them or a
 * password change ending every session. They are separate because the login
 * screen renders them differently: a notice must not mark the sign in fields
 * invalid, and a failure must not read like a receipt.
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

/**
 * How a registration attempt ended.
 *
 * 'closed' is not a failure. It means the API answered 404, so an admin account
 * exists and this deployment has had its one registration, whether it happened
 * a month ago or in the second between the form loading and the submit.
 */
export type RegisterOutcome = 'created' | 'closed' | 'failed';

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
  /** Something that happened and is worth saying, but is not a failure. */
  notice: string | null;
  /** Resolves true on success. Never throws: read error for the message. */
  login: (username: string, password: string) => Promise<boolean>;
  /**
   * Create the one admin account. Never throws.
   *
   * 'created' leaves a live session behind, so the caller does nothing further
   * and the console renders the dashboard. 'closed' means the caller should
   * show the sign in form; the reason is already in notice.
   */
  register: (
    username: string,
    password: string,
    bootstrapToken: string,
  ) => Promise<RegisterOutcome>;
  /**
   * Change the admin password, then end this session because the server ended
   * every other one. Resolves to null on success, or to the sentence to show
   * inside the dialog. Never throws.
   */
  changePassword: (currentPassword: string, newPassword: string) => Promise<string | null>;
  logout: () => Promise<void>;
}

const SESSION_ENDED_MESSAGE = 'Your admin session ended. Sign in again to continue.';

const LOCKED_MESSAGE =
  'This account is locked after too many failed attempts. Try again in about 15 minutes.';

const RATE_LIMITED_MESSAGE =
  'Too many sign in attempts from this network. Wait a few minutes and try again.';

/** Shown on the sign in form after the API closed registration under the user. */
export const REGISTRATION_CLOSED_MESSAGE =
  'An admin account already exists. Sign in instead.';

const PASSWORD_CHANGED_MESSAGE =
  'Your password was changed and every admin session was ended, including any other browser or device. Sign in with the new password.';

const BOOTSTRAP_TOKEN_MESSAGE =
  'That bootstrap token was not accepted. Copy the token from the API server console, or restart the API to print a fresh one: it is only valid for 30 minutes after startup.';

const REGISTER_RATE_LIMITED_MESSAGE =
  'Too many registration attempts from this network. This is limited to five an hour, so wait and then try again.';

const WEAK_PASSWORD_MESSAGE =
  'The API refused that password. Meet every rule in the checklist, then try again.';

const INVALID_DETAILS_MESSAGE =
  'The API refused those details. Check the username rules and the password rules below, then try again.';

const WRONG_CURRENT_PASSWORD_MESSAGE =
  'That current password did not match. Type it again, then retry.';

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

/**
 * The sentence shown under the registration form.
 *
 * The 404 case is missing on purpose: the caller turns that into a face swap
 * plus a notice, because there is nothing left to fix on this form.
 *
 * A weak_password detail is passed through word for word. It names the rule
 * that failed, and it is the operator's own new password, so being specific
 * costs nothing and saves a guessing game against a policy the client only
 * mirrors.
 */
function describeRegisterFailure(error: unknown): string {
  if (error instanceof AdminApiError) {
    if (error.isNetworkError) {
      return describeAdminError(error);
    }
    if (error.isRateLimited) {
      return REGISTER_RATE_LIMITED_MESSAGE;
    }
    if (error.isInvalidBootstrapToken || error.isUnauthorized) {
      return BOOTSTRAP_TOKEN_MESSAGE;
    }
    if (error.code === 'weak_password') {
      return error.detail !== '' ? error.detail : WEAK_PASSWORD_MESSAGE;
    }
    if (error.status === 422) {
      return error.detail !== '' ? error.detail : INVALID_DETAILS_MESSAGE;
    }
  }
  return describeAdminError(error);
}

/**
 * The sentence shown inside the change password dialog.
 *
 * A 401 here means the current password was wrong rather than that the session
 * expired: api.ts refreshes the access token immediately before sending, so an
 * expired token cannot reach this point. The one exception is a refresh the API
 * itself refused, which arrives with the no_session code and really is a dead
 * session.
 */
function describeChangePasswordFailure(error: unknown): string {
  if (error instanceof AdminApiError) {
    if (error.isNetworkError) {
      return describeAdminError(error);
    }
    if (error.code === 'no_session') {
      return SESSION_ENDED_MESSAGE;
    }
    if (error.isRateLimited) {
      return RATE_LIMITED_MESSAGE;
    }
    if (error.code === 'weak_password') {
      return error.detail !== '' ? error.detail : WEAK_PASSWORD_MESSAGE;
    }
    if (error.status === 422) {
      return error.detail !== '' ? error.detail : WEAK_PASSWORD_MESSAGE;
    }
    if (error.isUnauthorized) {
      return WRONG_CURRENT_PASSWORD_MESSAGE;
    }
  }
  return describeAdminError(error);
}

const AdminAuthContext = createContext<AdminAuth | null>(null);

export function AdminAuthProvider({ children }: { children: ReactNode }): JSX.Element {
  const [username, setUsername] = useState<string | null>(() => currentUsername());
  const [loading, setLoading] = useState<boolean>(() => hasStoredSession());
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Remembers what the last emit said, so a drop to null can be told apart
  // from a plain re-render and only a real drop writes the expiry message.
  const lastUsername = useRef<string | null>(currentUsername());

  // Raised just before this file ends a session on purpose, so the subscriber
  // does not write the generic expiry line over the specific reason.
  const intentionalSignOut = useRef(false);

  useEffect(() => {
    return subscribeToSession(() => {
      const next = currentUsername();
      const previous = lastUsername.current;
      const expected = intentionalSignOut.current;
      intentionalSignOut.current = false;
      lastUsername.current = next;
      setUsername(next);
      if (next === null && previous !== null && !expected) {
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

  const register = useCallback(
    async (name: string, password: string, bootstrapToken: string): Promise<RegisterOutcome> => {
      setError(null);
      setNotice(null);
      try {
        const signedIn = await adminApi.register(name, password, bootstrapToken);
        lastUsername.current = signedIn;
        setUsername(signedIn);
        return 'created';
      } catch (cause) {
        lastUsername.current = null;
        setUsername(null);
        if (cause instanceof AdminApiError && cause.isNotFound) {
          // Registration closed, either long ago or a moment ago. Either way
          // there is no form to correct, so this is a notice and not an error.
          setNotice(REGISTRATION_CLOSED_MESSAGE);
          return 'closed';
        }
        setError(describeRegisterFailure(cause));
        return 'failed';
      }
    },
    [],
  );

  const changePassword = useCallback(
    async (currentPassword: string, newPassword: string): Promise<string | null> => {
      try {
        await adminApi.changePassword(currentPassword, newPassword);
      } catch (cause) {
        return describeChangePasswordFailure(cause);
      }
      // The server revoked every admin refresh token, this tab's included, so
      // the session is already dead server-side. Dropping it locally is what
      // returns the console to the login form.
      intentionalSignOut.current = true;
      adminApi.endSession();
      lastUsername.current = null;
      setUsername(null);
      setError(null);
      setNotice(PASSWORD_CHANGED_MESSAGE);
      return null;
    },
    [],
  );

  const logout = useCallback(async (): Promise<void> => {
    intentionalSignOut.current = true;
    await adminApi.logout();
    lastUsername.current = null;
    setUsername(null);
    setError(null);
    setNotice(null);
  }, []);

  const value = useMemo<AdminAuth>(
    () => ({
      username,
      authed: username !== null,
      loading,
      error,
      notice,
      login,
      register,
      changePassword,
      logout,
    }),
    [username, loading, error, notice, login, register, changePassword, logout],
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
