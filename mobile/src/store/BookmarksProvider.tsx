/**
 * Bookmarks for this device, held in one place so the feed, search and saved
 * screens cannot disagree about what is saved.
 *
 * Bookmarks are per device with no account behind them: the server keys them on
 * the device id from the handshake, which is also why a device that loses its
 * credentials loses its saved articles.
 *
 * The toggle is optimistic. Tapping a bookmark on a full-screen card must flip
 * instantly, so the icon changes first and the request follows. When the request
 * fails the change is undone and the error is exposed for the screen to surface.
 * The rollback reverts only the article that failed, never a snapshot of the
 * whole set, so a second tap on another card while the first is in flight is not
 * silently thrown away.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from 'react';

import { api, describeError } from '@/src/api/client';
import { type ArticleCard } from '@/src/lib/types';

interface Snapshot {
  ids: Set<number>;
  items: ArticleCard[];
}

const EMPTY: Snapshot = { ids: new Set<number>(), items: [] };

export interface BookmarksState {
  /** Every saved article id, for a card that only needs the on/off state. */
  ids: ReadonlySet<number>;
  /** The saved articles, newest first. What the Saved screen renders. */
  items: ArticleCard[];
  /** True during the first load only. */
  loading: boolean;
  /** The last failure as a readable sentence, or null. */
  error: string | null;
  isBookmarked: (articleId: number) => boolean;
  /** True while this article's request is in flight, to disable the control. */
  isPending: (articleId: number) => boolean;
  /** Flips the article and resolves to its final state. Never throws. */
  toggle: (article: ArticleCard) => Promise<boolean>;
  /** Unsaves by id, for the swipe action on the Saved screen. Never throws. */
  remove: (articleId: number) => Promise<boolean>;
  /** Refetches the list, for pull to refresh. */
  refresh: () => Promise<void>;
}

const BookmarksContext = createContext<BookmarksState | null>(null);

/**
 * Applies a bookmark change to a snapshot without mutating the old one.
 *
 * `article` is optional because a screen can unsave by id alone. Without the
 * article there is nothing to put in the saved list, so only the id set changes
 * and the list catches up on the next refresh. Inventing a half-built
 * ArticleCard to fill the gap would crash whatever renders it.
 */
function withBookmark(
  snapshot: Snapshot,
  articleId: number,
  on: boolean,
  article?: ArticleCard | null,
): Snapshot {
  const ids = new Set(snapshot.ids);
  if (on) {
    ids.add(articleId);
    const present = snapshot.items.some((item) => item.id === articleId);
    if (present || !article) {
      return { ids, items: snapshot.items };
    }
    return { ids, items: [{ ...article, bookmarked: true }, ...snapshot.items] };
  }
  ids.delete(articleId);
  return { ids, items: snapshot.items.filter((item) => item.id !== articleId) };
}

export function BookmarksProvider({ children }: { children: ReactNode }): ReactElement {
  const [snapshot, setSnapshot] = useState<Snapshot>(EMPTY);
  const [pending, setPending] = useState<Set<number>>(() => new Set<number>());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // The state as of this instant, so an optimistic update can be computed from
  // the truth rather than from whatever the last render closed over.
  const current = useRef<Snapshot>(EMPTY);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const commit = useCallback((next: Snapshot) => {
    current.current = next;
    if (mounted.current) {
      setSnapshot(next);
    }
  }, []);

  const markPending = useCallback((articleId: number, on: boolean) => {
    if (!mounted.current) {
      return;
    }
    setPending((previous) => {
      const next = new Set(previous);
      if (on) {
        next.add(articleId);
      } else {
        next.delete(articleId);
      }
      return next;
    });
  }, []);

  const refresh = useCallback(async () => {
    try {
      const response = await api.listBookmarks();
      commit({
        ids: new Set(response.items.map((item) => item.id)),
        items: response.items,
      });
      if (mounted.current) {
        setError(null);
      }
    } catch (caught) {
      if (mounted.current) {
        setError(describeError(caught));
      }
    } finally {
      if (mounted.current) {
        setLoading(false);
      }
    }
  }, [commit]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const write = useCallback(
    async (articleId: number, on: boolean, article?: ArticleCard | null): Promise<boolean> => {
      // Captured before the optimistic write, so a rollback can put the article
      // back into the saved list rather than only restoring its id.
      const restored = article ?? current.current.items.find((item) => item.id === articleId);

      commit(withBookmark(current.current, articleId, on, article));
      markPending(articleId, true);

      try {
        const response = on ? await api.addBookmark(articleId) : await api.removeBookmark(articleId);
        if (mounted.current) {
          setError(null);
        }
        // The server is the authority: if it disagrees, follow it.
        if (response.bookmarked !== on) {
          commit(withBookmark(current.current, articleId, response.bookmarked, restored));
        }
        return response.bookmarked;
      } catch (caught) {
        commit(withBookmark(current.current, articleId, !on, restored));
        if (mounted.current) {
          setError(describeError(caught));
        }
        return !on;
      } finally {
        markPending(articleId, false);
      }
    },
    [commit, markPending],
  );

  const toggle = useCallback(
    (article: ArticleCard): Promise<boolean> =>
      write(article.id, !current.current.ids.has(article.id), article),
    [write],
  );

  const remove = useCallback(
    (articleId: number): Promise<boolean> => write(articleId, false),
    [write],
  );

  const value = useMemo<BookmarksState>(
    () => ({
      ids: snapshot.ids,
      items: snapshot.items,
      loading,
      error,
      isBookmarked: (articleId: number) => snapshot.ids.has(articleId),
      isPending: (articleId: number) => pending.has(articleId),
      toggle,
      remove,
      refresh,
    }),
    [snapshot, pending, loading, error, toggle, remove, refresh],
  );

  return <BookmarksContext.Provider value={value}>{children}</BookmarksContext.Provider>;
}

export function useBookmarks(): BookmarksState {
  const value = useContext(BookmarksContext);
  if (value === null) {
    throw new Error('useBookmarks must be used inside BookmarksProvider.');
  }
  return value;
}
