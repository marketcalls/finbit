/**
 * The single shared source of bookmark truth, contract section 11.
 * Feed, Search and Saved all read the same set of saved article ids, so a save
 * made on one screen is visible immediately on the others.
 *
 * Bookmarks are per device: the API keys them off the X-Device-Id header and
 * there is no login.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { ApiError, getBookmarks, addBookmark, removeBookmark, isAbortError } from '../api/client';

export interface BookmarksValue {
  /** Ids of every article saved on this device. */
  ids: Set<number>;
  isSaved: (articleId: number) => boolean;
  /** Optimistic save or unsave. Resolves to the saved state after the call. */
  toggle: (articleId: number) => Promise<boolean>;
  /** True while the initial list is loading. */
  loading: boolean;
  /** Last failure, cleared on the next successful call. */
  error: string | null;
  /** Reloads the saved list from the API. */
  refresh: () => Promise<void>;
}

const BookmarksContext = createContext<BookmarksValue | null>(null);

function describe(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error && error.message !== '') {
    return error.message;
  }
  return fallback;
}

export function BookmarksProvider({ children }: { children: ReactNode }): JSX.Element {
  const idsRef = useRef<Set<number>>(new Set<number>());
  const [ids, setIds] = useState<Set<number>>(idsRef.current);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef<Set<number>>(new Set<number>());

  const commitIds = useCallback((next: Set<number>) => {
    idsRef.current = next;
    setIds(next);
  }, []);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      try {
        const response = await getBookmarks({ signal });
        commitIds(new Set(response.items.map((item) => item.id)));
        setError(null);
      } catch (err) {
        if (isAbortError(err)) {
          return;
        }
        setError(describe(err, 'Could not load your saved stories.'));
      } finally {
        if (!signal?.aborted) {
          setLoading(false);
        }
      }
    },
    [commitIds],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => {
      controller.abort();
    };
  }, [load]);

  const refresh = useCallback(async () => {
    await load();
  }, [load]);

  const setSaved = useCallback(
    (articleId: number, saved: boolean) => {
      const next = new Set(idsRef.current);
      if (saved) {
        next.add(articleId);
      } else {
        next.delete(articleId);
      }
      commitIds(next);
    },
    [commitIds],
  );

  const toggle = useCallback(
    async (articleId: number): Promise<boolean> => {
      // Ignore a second tap while the first call is still in flight.
      if (pending.current.has(articleId)) {
        return idsRef.current.has(articleId);
      }

      const wasSaved = idsRef.current.has(articleId);
      const wanted = !wasSaved;

      pending.current.add(articleId);
      setSaved(articleId, wanted);
      setError(null);

      try {
        const response = wanted ? await addBookmark(articleId) : await removeBookmark(articleId);
        // The API is the authority, so settle on whatever it reports.
        setSaved(articleId, response.bookmarked);
        return response.bookmarked;
      } catch (err) {
        setSaved(articleId, wasSaved);
        if (!isAbortError(err)) {
          setError(
            describe(err, wanted ? 'Could not save that story.' : 'Could not remove that story.'),
          );
        }
        return wasSaved;
      } finally {
        pending.current.delete(articleId);
      }
    },
    [setSaved],
  );

  const isSaved = useCallback((articleId: number) => ids.has(articleId), [ids]);

  const value = useMemo<BookmarksValue>(
    () => ({ ids, isSaved, toggle, loading, error, refresh }),
    [ids, isSaved, toggle, loading, error, refresh],
  );

  return <BookmarksContext.Provider value={value}>{children}</BookmarksContext.Provider>;
}

/** Reads the shared bookmark state. Must be called inside a BookmarksProvider. */
export function useBookmarks(): BookmarksValue {
  const value = useContext(BookmarksContext);
  if (!value) {
    throw new Error('useBookmarks must be used inside a BookmarksProvider.');
  }
  return value;
}
