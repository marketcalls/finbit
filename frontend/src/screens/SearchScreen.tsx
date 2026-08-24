/**
 * Search screen, contract section 11.
 *
 * The input is debounced 300 ms and the API needs at least two characters. When
 * the box is empty the screen offers the trending symbols and topics from
 * /api/trending as one-tap queries. Results reuse the feed card in compact mode
 * in a normal scrolling list, and the result count is announced politely.
 */

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { ApiError, getTrending, isAbortError, search as searchApi } from '../api/client';
import type { ArticleCard, TrendingResponse } from '../api/types';
import { useRefreshSignal } from '../components/AppShell';
import { EmptyState } from '../components/EmptyState';
import { ErrorState } from '../components/ErrorState';
import { NewsCard } from '../components/NewsCard';
import { IconClose, IconSearch } from '../components/Icons';

/** Contract section 11: the input is debounced 300 ms. */
const DEBOUNCE_MS = 300;
/** Contract section 5: GET /api/search returns 422 below two characters. */
const MIN_QUERY_LENGTH = 2;
const RESULT_LIMIT = 30;

type SearchStatus = 'idle' | 'loading' | 'ready' | 'error';

const EMPTY_TRENDING: TrendingResponse = { symbols: [], topics: [] };

const CHIP_CLASS =
  'relative inline-flex items-center rounded-md border border-border bg-muted px-2.5 py-1.5 text-xs font-medium tracking-wide text-fg transition-colors duration-150 hover:border-accent hover:bg-card ' +
  "after:absolute after:inset-x-0 after:top-1/2 after:h-11 after:-translate-y-1/2 after:content-['']";

/*
  The trailing clear button in the markup below is the labelled 44 px version of
  the cross Chrome draws by itself for type="search", so the native one is
  hidden rather than showing the user two crosses side by side.
*/
const INPUT_CLASS =
  'h-12 w-full rounded-xl border border-border bg-card pl-11 pr-12 text-base text-fg placeholder:text-muted-fg ' +
  '[&::-webkit-search-cancel-button]:hidden [&::-webkit-search-decoration]:hidden';

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.isNetworkError
      ? 'Could not reach the FinBit API. Check that the backend is running, then try again.'
      : error.message;
  }
  if (error instanceof Error && error.message !== '') {
    return error.message;
  }
  return 'Search failed. Please try again.';
}

/** Placeholder cards, so the first paint is never a bare spinner. */
function ResultSkeleton(): JSX.Element {
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

export function SearchScreen(): JSX.Element {
  const inputId = useId();
  const symbolsHeadingId = useId();
  const topicsHeadingId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const refreshSignal = useRefreshSignal();

  const [query, setQuery] = useState('');
  const [term, setTerm] = useState('');
  const [items, setItems] = useState<ArticleCard[]>([]);
  const [count, setCount] = useState(0);
  const [status, setStatus] = useState<SearchStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [trending, setTrending] = useState<TrendingResponse>(EMPTY_TRENDING);
  const [retryToken, setRetryToken] = useState(0);

  // Debounce the typed query into the term that actually hits the API.
  useEffect(() => {
    const trimmed = query.trim();
    const timer = window.setTimeout(() => setTerm(trimmed), DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [query]);

  useEffect(() => {
    if (term.length < MIN_QUERY_LENGTH) {
      setItems([]);
      setCount(0);
      setError(null);
      setStatus('idle');
      return;
    }

    const controller = new AbortController();
    setStatus('loading');
    setError(null);

    searchApi(term, { signal: controller.signal, limit: RESULT_LIMIT })
      .then((response) => {
        setItems(response.items);
        setCount(response.count);
        setStatus('ready');
      })
      .catch((cause: unknown) => {
        if (isAbortError(cause)) {
          return;
        }
        setItems([]);
        setCount(0);
        setError(describeError(cause));
        setStatus('error');
      });

    return () => {
      controller.abort();
    };
  }, [term, refreshSignal, retryToken]);

  // Trending is a convenience, so a failure here just leaves the rails empty.
  useEffect(() => {
    const controller = new AbortController();

    getTrending({ signal: controller.signal })
      .then((response) => {
        setTrending({
          symbols: Array.isArray(response.symbols) ? response.symbols : [],
          topics: Array.isArray(response.topics) ? response.topics : [],
        });
      })
      .catch((cause: unknown) => {
        if (!isAbortError(cause)) {
          setTrending(EMPTY_TRENDING);
        }
      });

    return () => {
      controller.abort();
    };
  }, [refreshSignal, retryToken]);

  const runNow = useCallback((next: string) => {
    const trimmed = next.trim();
    setQuery(trimmed);
    setTerm(trimmed);
  }, []);

  const onSubmit = useCallback(
    (event: { preventDefault: () => void }) => {
      // The results already update as the user types, so submitting only skips
      // the remaining debounce and lets a mobile keyboard close.
      event.preventDefault();
      runNow(query);
      inputRef.current?.blur();
    },
    [query, runNow],
  );

  const clear = useCallback(() => {
    setQuery('');
    setTerm('');
    setItems([]);
    setCount(0);
    setError(null);
    setStatus('idle');
    inputRef.current?.focus();
  }, []);

  const retry = useCallback(() => {
    setRetryToken((token) => token + 1);
  }, []);

  const announcement = useMemo(() => {
    if (status === 'loading') {
      return `Searching for ${term}…`;
    }
    if (status === 'ready') {
      return `${count} ${count === 1 ? 'result' : 'results'} for ${term}`;
    }
    if (query.trim() !== '' && term.length < MIN_QUERY_LENGTH) {
      return `Type at least ${MIN_QUERY_LENGTH} characters to search.`;
    }
    return '';
  }, [status, term, count, query]);

  const hasTrending = trending.symbols.length > 0 || trending.topics.length > 0;
  const showTrending = query.trim() === '' && hasTrending;
  const showPrompt = term.length < MIN_QUERY_LENGTH && status !== 'error';

  return (
    <div className="mx-auto flex w-full max-w-[480px] flex-1 flex-col">
      <h1 className="sr-only">Search FinBit</h1>

      <div className="sticky top-14 z-30 border-b border-border bg-bg/95 px-4 py-3 backdrop-blur">
        <form role="search" onSubmit={onSubmit}>
          <label htmlFor={inputId} className="sr-only">
            Search stories by headline, symbol or topic
          </label>
          <div className="relative">
            <IconSearch className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-fg" />
            <input
              id={inputId}
              ref={inputRef}
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              autoComplete="off"
              spellCheck={false}
              enterKeyHint="search"
              placeholder="Search headlines, symbols, topics…"
              className={INPUT_CLASS}
            />
            {query !== '' ? (
              <button
                type="button"
                onClick={clear}
                aria-label="Clear the search"
                className="absolute right-0.5 top-1/2 inline-flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-lg text-muted-fg transition-colors duration-150 hover:bg-muted hover:text-fg"
              >
                <IconClose className="h-5 w-5" />
              </button>
            ) : null}
          </div>
        </form>

        <p role="status" aria-live="polite" className="mt-2 min-h-4 text-xs text-muted-fg">
          {announcement}
        </p>
      </div>

      <div className="flex-1 px-4 py-4">
        {status === 'error' && error !== null ? <ErrorState message={error} onRetry={retry} /> : null}

        {status === 'loading' ? <ResultSkeleton /> : null}

        {status === 'ready' && items.length > 0 ? (
          <ul className="flex flex-col gap-3">
            {items.map((article) => (
              <li key={article.id}>
                <NewsCard article={article} compact onSelectSymbol={runNow} />
              </li>
            ))}
          </ul>
        ) : null}

        {status === 'ready' && items.length === 0 ? (
          <EmptyState
            title="No results"
            body={`Nothing matched "${term}". Try a shorter query, a ticker such as RELIANCE, or a topic such as RBI Policy.`}
            action={{ label: 'Clear the search', onClick: clear }}
          />
        ) : null}

        {showTrending ? (
          <div className="flex flex-col gap-5">
            {trending.symbols.length > 0 ? (
              <section aria-labelledby={symbolsHeadingId}>
                <h2
                  id={symbolsHeadingId}
                  className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-fg"
                >
                  Trending symbols
                </h2>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {trending.symbols.map((symbol) => (
                    <li key={symbol}>
                      <button
                        type="button"
                        onClick={() => runNow(symbol)}
                        className={`${CHIP_CLASS} tnum`}
                      >
                        {symbol}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {trending.topics.length > 0 ? (
              <section aria-labelledby={topicsHeadingId}>
                <h2
                  id={topicsHeadingId}
                  className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-fg"
                >
                  Trending topics
                </h2>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {trending.topics.map((topic) => (
                    <li key={topic}>
                      <button type="button" onClick={() => runNow(topic)} className={CHIP_CLASS}>
                        {topic}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>
        ) : null}

        {showPrompt ? (
          <EmptyState
            title="Search FinBit"
            body={`Find a story by headline, summary, symbol or topic. Type at least ${MIN_QUERY_LENGTH} characters, for example RELIANCE, repo rate or Q1 results.`}
          />
        ) : null}
      </div>
    </div>
  );
}
