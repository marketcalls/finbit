/**
 * The FinBit feed, contract sections 10 and 11.
 *
 * One card per viewport in a vertical scroll-snap column, with category tabs,
 * market quick filters, a sort toggle, cursor paging through an
 * IntersectionObserver sentinel, and keyboard navigation.
 *
 * The height is pinned to the viewport minus the app chrome (a 3.5rem header,
 * plus the 4.5rem mobile tab bar that AppShell already pads for) so the feed
 * scrolls inside its own column and the page itself never scrolls.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, getCategories, getFeed, isAbortError } from '../api/client';
import type {
  ArticleCard,
  CategoryInfo,
  CategoryKey,
  FeedSort,
  MarketFilterInfo,
} from '../api/types';
import { requestRefresh, useRefreshSignal } from '../components/AppShell';
import {
  CATEGORY_LABELS,
  CategoryTabs,
  DEFAULT_CATEGORIES,
  categoryTabId,
} from '../components/CategoryTabs';
import { DEFAULT_MARKET_FILTERS, MarketFilters } from '../components/MarketFilters';
import { EmptyState } from '../components/EmptyState';
import { ErrorState } from '../components/ErrorState';
import { FeedSkeleton } from '../components/FeedSkeleton';
import { NewsCard } from '../components/NewsCard';

const PAGE_SIZE = 20;
const PANEL_ID = 'feed-panel';
const SORTS: Array<{ key: FeedSort; label: string; title: string }> = [
  { key: 'top', label: 'Top', title: 'Sort by importance' },
  { key: 'latest', label: 'Latest', title: 'Sort by publication time' },
];

/*
  The AppShell header is 3.5rem tall plus its 1px bottom border. On mobile
  AppShell also pads main by 4.5rem plus the safe area for the bottom tab bar,
  and that padding is gone from md upwards. Subtracting exactly that leaves the
  page itself with nothing to scroll, so only the feed column scrolls.
*/
const FEED_HEIGHT =
  'h-[calc(100dvh_-_3.5rem_-_1px_-_4.5rem_-_env(safe-area-inset-bottom))] md:h-[calc(100dvh_-_3.5rem_-_1px)]';

type FeedStatus = 'loading' | 'ready' | 'error';

function describe(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error && error.message !== '') {
    return error.message;
  }
  return fallback;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

/** Keeps paging idempotent if a cursor ever hands back a row we already hold. */
function mergeUnique(current: ArticleCard[], incoming: ArticleCard[]): ArticleCard[] {
  const seen = new Set(current.map((item) => item.id));
  const added = incoming.filter((item) => !seen.has(item.id));
  return added.length === 0 ? current : [...current, ...added];
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  if (target.isContentEditable) {
    return true;
  }
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
}

export function FeedScreen(): JSX.Element {
  const refreshSignal = useRefreshSignal();

  const [category, setCategory] = useState<CategoryKey>('all');
  const [symbol, setSymbol] = useState<string | null>(null);
  const [sort, setSort] = useState<FeedSort>('top');

  const [categories, setCategories] = useState<CategoryInfo[]>(DEFAULT_CATEGORIES);
  const [marketFilters, setMarketFilters] = useState<MarketFilterInfo[]>(DEFAULT_MARKET_FILTERS);

  const [items, setItems] = useState<ArticleCard[]>([]);
  const [status, setStatus] = useState<FeedStatus>('loading');
  const [error, setError] = useState<string | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const sentinelRef = useRef<HTMLLIElement | null>(null);
  const requestId = useRef(0);

  /* Category counts and market filter labels, with the contract defaults as a
     fallback so the tabs render even when the API is down. */
  useEffect(() => {
    const controller = new AbortController();
    getCategories({ signal: controller.signal })
      .then((response) => {
        if (response.categories.length > 0) {
          setCategories(response.categories);
        }
        if (response.market_filters.length > 0) {
          setMarketFilters(response.market_filters);
        }
      })
      .catch(() => {
        // The defaults already on screen are good enough. Nothing to report.
      });
    return () => {
      controller.abort();
    };
  }, [refreshSignal]);

  /* First page, and every reload after a filter, sort or refresh change. */
  useEffect(() => {
    const controller = new AbortController();
    const id = requestId.current + 1;
    requestId.current = id;

    setStatus('loading');
    setError(null);
    setMoreError(null);
    setLoadingMore(false);
    setItems([]);
    setCursor(null);
    setHasMore(false);

    getFeed(
      { category, symbol: symbol ?? undefined, sort, limit: PAGE_SIZE },
      { signal: controller.signal },
    )
      .then((response) => {
        if (id !== requestId.current) {
          return;
        }
        setItems(response.items);
        setCursor(response.next_cursor);
        setHasMore(response.has_more && response.next_cursor !== null);
        setStatus('ready');
        scrollRef.current?.scrollTo({ top: 0 });
      })
      .catch((err: unknown) => {
        if (isAbortError(err) || id !== requestId.current) {
          return;
        }
        setError(describe(err, 'Could not load the feed.'));
        setStatus('error');
      });

    return () => {
      controller.abort();
    };
  }, [category, symbol, sort, refreshSignal]);

  const loadMore = useCallback(() => {
    if (status !== 'ready' || !hasMore || cursor === null || loadingMore || moreError !== null) {
      return;
    }
    const id = requestId.current;
    setLoadingMore(true);

    getFeed({ category, symbol: symbol ?? undefined, sort, cursor, limit: PAGE_SIZE })
      .then((response) => {
        if (id !== requestId.current) {
          return;
        }
        setItems((previous) => mergeUnique(previous, response.items));
        setCursor(response.next_cursor);
        setHasMore(response.has_more && response.next_cursor !== null);
        setLoadingMore(false);
      })
      .catch((err: unknown) => {
        if (id !== requestId.current) {
          return;
        }
        setLoadingMore(false);
        if (!isAbortError(err)) {
          setMoreError(describe(err, 'Could not load more stories.'));
        }
      });
  }, [category, cursor, hasMore, loadingMore, moreError, sort, status, symbol]);

  /* Infinite scroll: watch a sentinel at the end of the list. */
  useEffect(() => {
    const root = scrollRef.current;
    const sentinel = sentinelRef.current;
    if (!root || !sentinel || typeof IntersectionObserver === 'undefined') {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          loadMore();
        }
      },
      { root, rootMargin: '600px 0px', threshold: 0 },
    );
    observer.observe(sentinel);

    return () => {
      observer.disconnect();
    };
  }, [loadMore, items.length, status]);

  /* Keyboard navigation, card to card. */
  const cardElements = useCallback((): HTMLElement[] => {
    const root = scrollRef.current;
    if (!root) {
      return [];
    }
    return Array.from(root.querySelectorAll<HTMLElement>('[data-feed-card]'));
  }, []);

  const currentIndex = useCallback((): number => {
    const root = scrollRef.current;
    const cards = cardElements();
    if (!root || cards.length === 0) {
      return 0;
    }
    const top = root.scrollTop;
    let best = 0;
    let bestDistance = Number.POSITIVE_INFINITY;
    cards.forEach((card, index) => {
      const distance = Math.abs(card.offsetTop - top);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = index;
      }
    });
    return best;
  }, [cardElements]);

  const moveTo = useCallback(
    (index: number): boolean => {
      const cards = cardElements();
      if (cards.length === 0) {
        return false;
      }
      const clamped = Math.min(Math.max(index, 0), cards.length - 1);
      cards[clamped].scrollIntoView({
        behavior: prefersReducedMotion() ? 'auto' : 'smooth',
        block: 'start',
      });
      return true;
    },
    [cardElements],
  );

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) {
        return;
      }
      if (isTypingTarget(event.target)) {
        return;
      }

      let handled = false;
      switch (event.key) {
        case 'ArrowDown':
        case 'PageDown':
        case 'j':
          handled = moveTo(currentIndex() + 1);
          break;
        case 'ArrowUp':
        case 'PageUp':
        case 'k':
          handled = moveTo(currentIndex() - 1);
          break;
        case 'Home':
          handled = moveTo(0);
          break;
        case 'End':
          handled = moveTo(Number.MAX_SAFE_INTEGER);
          break;
        default:
          return;
      }

      if (handled) {
        event.preventDefault();
      }
    }

    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [currentIndex, moveTo]);

  /** Chips and market filters both toggle: choosing the active one clears it. */
  const toggleSymbol = useCallback((next: string) => {
    setSymbol((previous) => (previous === next ? null : next));
  }, []);

  const clearFilters = useCallback(() => {
    setCategory('all');
    setSymbol(null);
  }, []);

  const filtered = category !== 'all' || symbol !== null;

  const filterSummary = useMemo(() => {
    if (category !== 'all' && symbol) {
      return `Nothing under ${CATEGORY_LABELS[category]} tagged ${symbol} right now.`;
    }
    if (symbol) {
      return `Nothing tagged ${symbol} right now.`;
    }
    return `Nothing under ${CATEGORY_LABELS[category]} right now.`;
  }, [category, symbol]);

  const liveMessage = useMemo(() => {
    if (status === 'loading') {
      return 'Loading stories.';
    }
    if (status === 'error') {
      // ErrorState is itself an alert, so leave the announcement to it.
      return '';
    }
    if (items.length === 0) {
      return 'No stories to show.';
    }
    if (loadingMore) {
      return 'Loading more stories.';
    }
    if (!hasMore) {
      return `Showing ${items.length} stories. No more stories.`;
    }
    return `Showing ${items.length} stories.`;
  }, [hasMore, items.length, loadingMore, status]);

  let panel: JSX.Element;
  if (status === 'loading') {
    panel = <FeedSkeleton count={2} />;
  } else if (status === 'error') {
    panel = (
      <div className="mx-auto flex h-full w-full max-w-[480px] items-center justify-center p-4">
        <ErrorState
          message={error ?? 'The feed could not be loaded.'}
          onRetry={() => requestRefresh()}
        />
      </div>
    );
  } else if (items.length === 0) {
    panel = (
      <div className="mx-auto flex h-full w-full max-w-[480px] items-center justify-center p-4">
        {filtered ? (
          <EmptyState
            title="No stories match these filters"
            body={`${filterSummary} Clear the filters to see the whole feed.`}
            action={{ label: 'Clear filters', onClick: clearFilters }}
          />
        ) : (
          <EmptyState
            title="The feed is empty"
            body="Nothing has been ingested yet. FinBit fills this feed from the news pipeline, so the first stories appear once an ingest run has finished. Refresh to check again."
            action={{ label: 'Refresh', onClick: () => requestRefresh() }}
          />
        )}
      </div>
    );
  } else {
    panel = (
      <ol className="mx-auto h-full w-full max-w-[480px]">
        {items.map((article) => (
          <li key={article.id} data-feed-card className="flex min-h-full flex-col">
            <NewsCard article={article} onSelectSymbol={toggleSymbol} />
          </li>
        ))}
        <li
          ref={sentinelRef}
          className="flex min-h-24 flex-col items-center justify-center gap-3 px-5 py-8 text-center text-xs text-muted-fg"
        >
          {loadingMore ? <span>Loading more stories.</span> : null}
          {!loadingMore && moreError !== null ? (
            <>
              <span>{moreError}</span>
              <button
                type="button"
                onClick={() => setMoreError(null)}
                className="inline-flex min-h-11 items-center rounded-md border border-border px-4 text-sm font-medium text-fg transition-colors duration-150 hover:bg-muted"
              >
                Try again
              </button>
            </>
          ) : null}
          {!loadingMore && moreError === null && !hasMore ? (
            <span>You are up to date. No more stories.</span>
          ) : null}
        </li>
      </ol>
    );
  }

  return (
    <section aria-label="News feed" className={`flex w-full flex-col ${FEED_HEIGHT}`}>
      <div className="flex-none border-b border-border bg-bg">
        <CategoryTabs
          categories={categories}
          active={category}
          onChange={setCategory}
          panelId={PANEL_ID}
        />
        <div className="flex items-center gap-2 px-2 pb-2">
          <div className="min-w-0 flex-1">
            <MarketFilters filters={marketFilters} active={symbol} onToggle={toggleSymbol} />
          </div>
          <div
            role="group"
            aria-label="Sort stories"
            className="flex flex-none items-center gap-1 border-l border-border pl-2"
          >
            {SORTS.map((option) => {
              const pressed = option.key === sort;
              return (
                <button
                  key={option.key}
                  type="button"
                  aria-pressed={pressed}
                  title={option.title}
                  onClick={() => setSort(option.key)}
                  className={`inline-flex min-h-11 items-center rounded-md px-2.5 text-xs font-semibold transition-colors duration-150 ${
                    pressed ? 'bg-muted text-fg' : 'text-muted-fg hover:text-fg'
                  }`}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <p aria-live="polite" className="sr-only">
        {liveMessage}
      </p>

      <div
        ref={scrollRef}
        id={PANEL_ID}
        role="tabpanel"
        aria-labelledby={categoryTabId(category)}
        tabIndex={0}
        className="feed-scroll relative min-h-0 flex-1 overflow-y-auto"
      >
        {panel}
      </div>

      <p className="hidden flex-none border-t border-border px-4 py-1.5 text-center text-[11px] text-muted-fg md:block">
        Press j or the down arrow for the next story, k or the up arrow for the previous one.
      </p>
    </section>
  );
}
