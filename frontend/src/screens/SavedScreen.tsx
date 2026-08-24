/**
 * Saved screen, contract section 11.
 *
 * Reads GET /api/bookmarks and renders the feed card in compact mode. Unsaving
 * runs through the shared BookmarksProvider, which is optimistic and rolls back
 * on failure, so this screen simply renders the stories the shared set still
 * holds: a successful unsave removes the card immediately, and a failed one
 * puts it back. Bookmarks are keyed to the device id, so there is no login.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, getBookmarks, isAbortError } from '../api/client';
import type { ArticleCard } from '../api/types';
import { useRefreshSignal } from '../components/AppShell';
import { EmptyState } from '../components/EmptyState';
import { ErrorState } from '../components/ErrorState';
import { NewsCard } from '../components/NewsCard';
import { useBookmarks } from '../lib/bookmarks';

type LoadStatus = 'loading' | 'ready' | 'error';

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.isNetworkError
      ? 'Could not reach the FinBit API. Check that the backend is running, then try again.'
      : error.message;
  }
  if (error instanceof Error && error.message !== '') {
    return error.message;
  }
  return 'Could not load your saved stories. Please try again.';
}

/** Placeholder cards, so the first paint is never a bare spinner. */
function SavedSkeleton(): JSX.Element {
  return (
    <ul aria-hidden="true" className="flex flex-col gap-3">
      {[0, 1, 2].map((row) => (
        <li key={row} className="animate-pulse rounded-xl border border-border bg-card p-4">
          <div className="h-3 w-24 rounded bg-muted" />
          <div className="mt-3 h-4 w-full rounded bg-muted" />
          <div className="mt-2 h-4 w-4/5 rounded bg-muted" />
          <div className="mt-4 h-3 w-2/3 rounded bg-muted" />
        </li>
      ))}
    </ul>
  );
}

export function SavedScreen(): JSX.Element {
  const refreshSignal = useRefreshSignal();
  const { ids, loading: bookmarksLoading, error: bookmarksError } = useBookmarks();

  const [items, setItems] = useState<ArticleCard[]>([]);
  const [status, setStatus] = useState<LoadStatus>('loading');
  const [error, setError] = useState<string | null>(null);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setStatus('loading');
    setError(null);

    getBookmarks({ signal: controller.signal })
      .then((response) => {
        setItems(Array.isArray(response.items) ? response.items : []);
        setStatus('ready');
      })
      .catch((cause: unknown) => {
        if (isAbortError(cause)) {
          return;
        }
        setItems([]);
        setError(describeError(cause));
        setStatus('error');
      });

    return () => {
      controller.abort();
    };
  }, [refreshSignal, retryToken]);

  /*
    While the shared set is still loading, or has failed, show exactly what the
    API returned. Once it is settled it is the authority, which is what makes an
    unsave feel instant and a failed unsave restore the card.
  */
  const visible = useMemo(() => {
    if (bookmarksLoading || bookmarksError !== null) {
      return items;
    }
    return items.filter((item) => ids.has(item.id));
  }, [items, ids, bookmarksLoading, bookmarksError]);

  const retry = useCallback(() => {
    setRetryToken((token) => token + 1);
  }, []);

  const count = visible.length;
  const announcement =
    status === 'loading'
      ? 'Loading your saved stories.'
      : status === 'ready'
        ? `${count} saved ${count === 1 ? 'story' : 'stories'}`
        : '';

  return (
    <div className="mx-auto flex w-full max-w-[480px] flex-1 flex-col px-4 py-4">
      <div className="flex items-baseline justify-between gap-3">
        <h1 className="font-headline text-2xl font-semibold text-fg">Saved</h1>
        <p role="status" aria-live="polite" className="text-xs text-muted-fg tnum">
          {announcement}
        </p>
      </div>

      <div className="mt-4 flex flex-1 flex-col gap-3">
        {status === 'error' && error !== null ? <ErrorState message={error} onRetry={retry} /> : null}

        {status === 'loading' ? <SavedSkeleton /> : null}

        {/*
          Only while the list itself loaded: this banner reports a save or an
          unsave that failed and rolled back. When the whole load failed the
          ErrorState above already says so, and both would say the same thing.
        */}
        {status === 'ready' && bookmarksError !== null ? (
          <p
            role="status"
            aria-live="polite"
            className="rounded-lg border border-bear/40 bg-bear/10 px-3 py-2 text-sm text-fg"
          >
            {bookmarksError}
          </p>
        ) : null}

        {status === 'ready' && count > 0 ? (
          <ul className="flex flex-col gap-3">
            {visible.map((article) => (
              <li key={article.id}>
                <NewsCard article={article} compact />
              </li>
            ))}
          </ul>
        ) : null}

        {status === 'ready' && count === 0 ? (
          <EmptyState
            title="Nothing saved yet"
            body="Tap the bookmark icon on any story to keep it here. Saved stories live on this device only, so there is no login and nothing to sync."
          />
        ) : null}
      </div>
    </div>
  );
}
