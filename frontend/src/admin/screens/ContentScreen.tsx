/**
 * Content moderation: the article table, contract section 6.5 and section 9.
 *
 * Hiding and pinning are optimistic, because they are one boolean, they are
 * instantly reversible, and waiting a round trip to see a row grey out makes
 * moderating a list feel broken. Everything with a payload the client cannot
 * predict (an edit, a re-score, an image refresh) waits for the server and then
 * adopts what it sent back, since guessing a new importance score would just be
 * a lie that corrects itself a second later. Delete removes the row first and
 * puts it back on failure, which is the same bargain as the public feed's
 * optimistic unsave.
 *
 * One deliberate exception to filtering: hiding a story while the hidden filter
 * says "visible only" leaves the row on screen with a hidden badge rather than
 * making it disappear. Reloading the page under the operator's cursor to honour
 * a filter they set before the change costs more than the small inconsistency,
 * and the next load reconciles it anyway.
 *
 * Paging is cursor based, one Load more button rather than infinite scroll: an
 * admin table is something you scan and act on, not something you fall into.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Eye,
  EyeOff,
  Image as ImageIcon,
  Layers,
  LoaderCircle,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  RefreshCw,
  Search,
  Trash2,
} from 'lucide-react';

import {
  CATEGORIES,
  type AdminArticle,
  type AdminArticleParams,
  type AdminArticlePatch,
  type FeedCategory,
  type SortMode,
} from '@finbit/shared';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../../components/ui/dropdown-menu';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../components/ui/select';
import { toast } from '../../components/ui/sonner';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui/table';
import { absoluteTime, relativeTime } from '../../lib/format';
import { adminApi, describeAdminError, isAbortError } from '../api';
import { ArticleEditDialog } from '../components/ArticleEditDialog';
import { ClusterSheet } from '../components/ClusterSheet';
import { ConfirmAction } from '../components/ConfirmAction';
import { EmptyBlock, ErrorBlock, LoadingAnnouncement, TableSkeleton } from '../components/StateBlocks';

type LoadStatus = 'loading' | 'ready' | 'error';

/** A three way filter, because "either" is a real answer and false is not. */
type TriFilter = 'any' | 'yes' | 'no';

const PAGE_SIZE = 25;

const TRI_LABELS: Record<TriFilter, { hidden: string; pinned: string }> = {
  any: { hidden: 'Hidden: any', pinned: 'Pinned: any' },
  yes: { hidden: 'Hidden only', pinned: 'Pinned only' },
  no: { hidden: 'Visible only', pinned: 'Unpinned only' },
};

function triToBoolean(value: TriFilter): boolean | undefined {
  if (value === 'yes') {
    return true;
  }
  if (value === 'no') {
    return false;
  }
  return undefined;
}

export function ContentScreen(): JSX.Element {
  const [queryText, setQueryText] = useState('');
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<FeedCategory>('all');
  const [hiddenFilter, setHiddenFilter] = useState<TriFilter>('any');
  const [pinnedFilter, setPinnedFilter] = useState<TriFilter>('any');
  const [sort, setSort] = useState<SortMode>('top');

  const [items, setItems] = useState<AdminArticle[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [status, setStatus] = useState<LoadStatus>('loading');
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const [pending, setPending] = useState<ReadonlySet<number>>(new Set());

  const [editing, setEditing] = useState<AdminArticle | null>(null);
  const [clusterId, setClusterId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<AdminArticle | null>(null);

  // Typing must not fire a request per keystroke, contract section 11.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(queryText.trim());
    }, 300);
    return () => {
      window.clearTimeout(timer);
    };
  }, [queryText]);

  const params = useMemo<AdminArticleParams>(
    () => ({
      q: query === '' ? undefined : query,
      category: category === 'all' ? undefined : category,
      hidden: triToBoolean(hiddenFilter),
      pinned: triToBoolean(pinnedFilter),
      sort,
      limit: PAGE_SIZE,
    }),
    [query, category, hiddenFilter, pinnedFilter, sort],
  );

  useEffect(() => {
    const controller = new AbortController();
    setStatus('loading');
    setError(null);

    adminApi
      .listArticles(params, controller.signal)
      .then((response) => {
        setItems(response.items);
        setCursor(response.next_cursor);
        setHasMore(response.has_more);
        setStatus('ready');
      })
      .catch((cause: unknown) => {
        if (isAbortError(cause)) {
          return;
        }
        setItems([]);
        setCursor(null);
        setHasMore(false);
        setError(describeAdminError(cause));
        setStatus('error');
      });

    return () => {
      controller.abort();
    };
  }, [params, reloadToken]);

  const reload = useCallback(() => {
    setReloadToken((token) => token + 1);
  }, []);

  const markPending = useCallback((articleId: number, busy: boolean) => {
    setPending((current) => {
      const next = new Set(current);
      if (busy) {
        next.add(articleId);
      } else {
        next.delete(articleId);
      }
      return next;
    });
  }, []);

  const replaceItem = useCallback((updated: AdminArticle) => {
    setItems((list) => list.map((item) => (item.id === updated.id ? updated : item)));
  }, []);

  const filtersActive =
    query !== '' || category !== 'all' || hiddenFilter !== 'any' || pinnedFilter !== 'any';

  function clearFilters(): void {
    setQueryText('');
    setQuery('');
    setCategory('all');
    setHiddenFilter('any');
    setPinnedFilter('any');
  }

  async function loadMore(): Promise<void> {
    if (cursor === null || loadingMore) {
      return;
    }
    setLoadingMore(true);
    try {
      const response = await adminApi.listArticles({ ...params, cursor });
      setItems((list) => [...list, ...response.items]);
      setCursor(response.next_cursor);
      setHasMore(response.has_more);
    } catch (cause) {
      toast.error(describeAdminError(cause));
    } finally {
      setLoadingMore(false);
    }
  }

  /** Optimistic hide or pin, rolled back to the row we started from on failure. */
  async function toggleFlag(article: AdminArticle, flag: 'hidden' | 'pinned'): Promise<void> {
    const next = !article[flag];
    const patch: AdminArticlePatch = flag === 'hidden' ? { hidden: next } : { pinned: next };
    const optimistic: AdminArticle =
      flag === 'hidden' ? { ...article, hidden: next } : { ...article, pinned: next };

    replaceItem(optimistic);
    markPending(article.id, true);
    try {
      const updated = await adminApi.patchArticle(article.id, patch);
      replaceItem(updated);
      if (flag === 'hidden') {
        toast.success(next ? 'Story hidden' : 'Story is visible again');
      } else {
        toast.success(next ? 'Story pinned' : 'Story unpinned');
      }
    } catch (cause) {
      replaceItem(article);
      toast.error(describeAdminError(cause));
    } finally {
      markPending(article.id, false);
    }
  }

  async function saveEdit(articleId: number, patch: AdminArticlePatch): Promise<boolean> {
    markPending(articleId, true);
    try {
      const updated = await adminApi.patchArticle(articleId, patch);
      replaceItem(updated);
      toast.success('Story updated');
      return true;
    } catch (cause) {
      toast.error(describeAdminError(cause));
      return false;
    } finally {
      markPending(articleId, false);
    }
  }

  async function rescore(article: AdminArticle): Promise<void> {
    markPending(article.id, true);
    try {
      const result = await adminApi.rescoreArticle(article.id);
      replaceItem({ ...article, importance_score: result.importance_score });
      toast.success(`Re-scored to ${result.importance_score}`);
    } catch (cause) {
      toast.error(describeAdminError(cause));
    } finally {
      markPending(article.id, false);
    }
  }

  async function refreshImage(article: AdminArticle): Promise<void> {
    markPending(article.id, true);
    try {
      const result = await adminApi.refreshArticleImage(article.id);
      replaceItem({ ...article, image_url: result.image_url });
      toast.success(
        result.image_url === null
          ? 'No Open Graph image on any source page'
          : 'Image refreshed from the source page',
      );
    } catch (cause) {
      toast.error(describeAdminError(cause));
    } finally {
      markPending(article.id, false);
    }
  }

  async function confirmDelete(article: AdminArticle): Promise<void> {
    const previous = items;
    setItems((list) => list.filter((item) => item.id !== article.id));
    setDeleting(null);
    try {
      await adminApi.deleteArticle(article.id);
      toast.success('Story deleted');
    } catch (cause) {
      setItems(previous);
      toast.error(describeAdminError(cause));
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-headline text-2xl font-semibold">Content</h1>
        <p className="text-sm text-muted-fg" aria-live="polite">
          {status === 'ready'
            ? `${items.length} ${items.length === 1 ? 'story' : 'stories'}${hasMore ? ' so far' : ''}`
            : ''}
        </p>
      </div>

      {/* -- filters ------------------------------------------------------- */}
      <div className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor="content-search">Search stories</Label>
          <div className="relative">
            <Search
              aria-hidden="true"
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-fg"
            />
            <Input
              id="content-search"
              type="search"
              autoComplete="off"
              spellCheck={false}
              placeholder="Headline, summary, symbol or topic..."
              className="pl-9"
              value={queryText}
              onChange={(event) => {
                setQueryText(event.target.value);
              }}
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={category}
            onValueChange={(value) => {
              setCategory(value as FeedCategory);
            }}
          >
            <SelectTrigger size="sm" className="w-40" aria-label="Filter by category">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CATEGORIES.map((option) => (
                <SelectItem key={option.key} value={option.key}>
                  {option.key === 'all' ? 'All categories' : option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            value={hiddenFilter}
            onValueChange={(value) => {
              setHiddenFilter(value as TriFilter);
            }}
          >
            <SelectTrigger size="sm" className="w-40" aria-label="Filter by hidden state">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="any">{TRI_LABELS.any.hidden}</SelectItem>
              <SelectItem value="yes">{TRI_LABELS.yes.hidden}</SelectItem>
              <SelectItem value="no">{TRI_LABELS.no.hidden}</SelectItem>
            </SelectContent>
          </Select>

          <Select
            value={pinnedFilter}
            onValueChange={(value) => {
              setPinnedFilter(value as TriFilter);
            }}
          >
            <SelectTrigger size="sm" className="w-40" aria-label="Filter by pinned state">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="any">{TRI_LABELS.any.pinned}</SelectItem>
              <SelectItem value="yes">{TRI_LABELS.yes.pinned}</SelectItem>
              <SelectItem value="no">{TRI_LABELS.no.pinned}</SelectItem>
            </SelectContent>
          </Select>

          <Select
            value={sort}
            onValueChange={(value) => {
              setSort(value as SortMode);
            }}
          >
            <SelectTrigger size="sm" className="w-40" aria-label="Sort order">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="top">Sort: importance</SelectItem>
              <SelectItem value="latest">Sort: newest</SelectItem>
            </SelectContent>
          </Select>

          {filtersActive ? (
            <Button type="button" variant="ghost" size="sm" onClick={clearFilters}>
              Clear filters
            </Button>
          ) : null}
        </div>
      </div>

      {/* -- table --------------------------------------------------------- */}
      {status === 'loading' ? (
        <>
          <LoadingAnnouncement>Loading stories.</LoadingAnnouncement>
          <TableSkeleton rows={8} columns={5} />
        </>
      ) : null}

      {status === 'error' ? (
        <ErrorBlock
          title="Could not load the stories"
          message={error ?? 'The article list did not load.'}
          onRetry={reload}
        />
      ) : null}

      {status === 'ready' && items.length === 0 ? (
        <EmptyBlock
          title={filtersActive ? 'Nothing matches those filters' : 'No stories yet'}
          body={
            filtersActive
              ? 'No story matches the current search and filters. Clearing them shows everything again.'
              : 'The database has no articles. Run a discovery cycle from the Pipeline screen to fill it.'
          }
          action={filtersActive ? { label: 'Clear filters', onClick: clearFilters } : undefined}
        />
      ) : null}

      {status === 'ready' && items.length > 0 ? (
        <div className="rounded-xl border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Story</TableHead>
                <TableHead className="w-32">Category</TableHead>
                <TableHead className="w-20 text-right">Score</TableHead>
                <TableHead className="w-32">Published</TableHead>
                <TableHead className="w-16 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((article) => {
                const busy = pending.has(article.id);
                return (
                  <TableRow key={article.id} data-state={article.hidden ? 'selected' : undefined}>
                    <TableCell>
                      <div className="flex flex-wrap items-center gap-2">
                        {article.is_breaking ? (
                          <Badge className="bg-breaking text-on-breaking">breaking</Badge>
                        ) : null}
                        {article.hidden ? <Badge variant="flat">hidden</Badge> : null}
                        {article.pinned ? <Badge variant="bull">pinned</Badge> : null}
                        {busy ? (
                          <LoaderCircle
                            aria-label="Saving"
                            className="size-4 animate-spin text-muted-fg"
                          />
                        ) : null}
                      </div>
                      <p className="mt-1 max-w-xl text-sm font-medium text-fg">
                        {article.headline}
                      </p>
                      <p className="mt-1 text-xs text-muted-fg">
                        {article.source_count}{' '}
                        {article.source_count === 1 ? 'source' : 'sources'}
                        {article.moderated_by !== null
                          ? `, last touched by ${article.moderated_by}`
                          : ''}
                      </p>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{article.category}</Badge>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {article.importance_score}
                    </TableCell>
                    <TableCell title={absoluteTime(article.published_at)}>
                      {relativeTime(article.published_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            disabled={busy}
                            aria-label={`Actions for ${article.headline}`}
                          >
                            <MoreHorizontal aria-hidden="true" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem
                            onSelect={() => {
                              void toggleFlag(article, 'hidden');
                            }}
                          >
                            {article.hidden ? (
                              <Eye aria-hidden="true" />
                            ) : (
                              <EyeOff aria-hidden="true" />
                            )}
                            {article.hidden ? 'Unhide' : 'Hide'}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onSelect={() => {
                              void toggleFlag(article, 'pinned');
                            }}
                          >
                            {article.pinned ? (
                              <PinOff aria-hidden="true" />
                            ) : (
                              <Pin aria-hidden="true" />
                            )}
                            {article.pinned ? 'Unpin' : 'Pin'}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onSelect={() => {
                              setEditing(article);
                            }}
                          >
                            <Pencil aria-hidden="true" />
                            Edit
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            onSelect={() => {
                              void rescore(article);
                            }}
                          >
                            <RefreshCw aria-hidden="true" />
                            Re-score
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onSelect={() => {
                              void refreshImage(article);
                            }}
                          >
                            <ImageIcon aria-hidden="true" />
                            Refresh image
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onSelect={() => {
                              setClusterId(article.id);
                            }}
                          >
                            <Layers aria-hidden="true" />
                            View cluster
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            variant="destructive"
                            onSelect={() => {
                              setDeleting(article);
                            }}
                          >
                            <Trash2 aria-hidden="true" />
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      ) : null}

      {status === 'ready' && hasMore ? (
        <div className="flex justify-center">
          <Button
            type="button"
            variant="outline"
            disabled={loadingMore}
            onClick={() => {
              void loadMore();
            }}
          >
            {loadingMore ? <LoaderCircle aria-hidden="true" className="animate-spin" /> : null}
            Load more
          </Button>
        </div>
      ) : null}

      <ArticleEditDialog
        article={editing}
        onSave={saveEdit}
        onOpenChange={(open) => {
          if (!open) {
            setEditing(null);
          }
        }}
      />

      <ClusterSheet
        articleId={clusterId}
        onOpenChange={(open) => {
          if (!open) {
            setClusterId(null);
          }
        }}
      />

      <ConfirmAction
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) {
            setDeleting(null);
          }
        }}
        title="Delete this story?"
        confirmLabel="Delete"
        destructive
        description={
          <>
            <p>{deleting?.headline}</p>
            <p className="mt-2">
              Deleting removes the article, its sources, its symbols and its bookmarks. This cannot
              be undone. Hiding it keeps the record and takes it out of the feed.
            </p>
          </>
        }
        onConfirm={() => {
          if (deleting !== null) {
            void confirmDelete(deleting);
          }
        }}
      />
    </div>
  );
}
