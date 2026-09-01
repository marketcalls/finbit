/**
 * The dedupe cluster behind one story, contract section 6.5.
 *
 * A FinBit article is not one report: it is a cluster of paraphrases the
 * pipeline merged on a headline token overlap (CONTRACT.md section 7). When a
 * story looks wrong the first question is almost always "what actually merged
 * into this", so this panel puts the dedupe key, the cluster id, every source
 * link and every sibling in one place.
 *
 * It fetches on open rather than with the table. A cluster is several extra
 * joins per row and nobody opens one for most rows, so loading it up front
 * would slow the list down for a view that is rarely used.
 */

import { useEffect, useState } from 'react';

import type { ArticleClusterResponse } from '@finbit/shared';
import { Badge } from '../../components/ui/badge';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '../../components/ui/sheet';
import { Skeleton } from '../../components/ui/skeleton';
import { relativeTime, sourceHost } from '../../lib/format';
import { adminApi, describeAdminError, isAbortError } from '../api';
import { ErrorBlock } from './StateBlocks';

export interface ClusterSheetProps {
  /** The story whose cluster to show. Null closes the panel. */
  articleId: number | null;
  onOpenChange: (open: boolean) => void;
}

export function ClusterSheet({ articleId, onOpenChange }: ClusterSheetProps): JSX.Element {
  const [cluster, setCluster] = useState<ArticleClusterResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (articleId === null) {
      return;
    }
    const controller = new AbortController();
    setCluster(null);
    setError(null);

    adminApi
      .getCluster(articleId, controller.signal)
      .then((response) => {
        setCluster(response);
      })
      .catch((cause: unknown) => {
        if (isAbortError(cause)) {
          return;
        }
        setError(describeAdminError(cause));
      });

    return () => {
      controller.abort();
    };
  }, [articleId, reloadToken]);

  return (
    <Sheet open={articleId !== null} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>Story cluster</SheetTitle>
          <SheetDescription>
            {cluster !== null
              ? cluster.article.headline
              : 'The sources and sibling stories behind this article.'}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto px-4 pb-6">
          {error !== null ? (
            <ErrorBlock
              title="Could not load the cluster"
              message={error}
              onRetry={() => {
                setReloadToken((token) => token + 1);
              }}
            />
          ) : cluster === null ? (
            <div aria-hidden="true" className="flex flex-col gap-3">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ) : (
            <div className="flex flex-col gap-6">
              <dl className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <dt className="text-muted-fg">Dedupe key</dt>
                  <dd className="mt-1 break-all font-mono text-fg">{cluster.dedupe_key}</dd>
                </div>
                <div>
                  <dt className="text-muted-fg">Cluster id</dt>
                  <dd className="mt-1 break-all font-mono text-fg">{cluster.story_cluster_id}</dd>
                </div>
              </dl>

              <section aria-labelledby="cluster-sources">
                <h3 id="cluster-sources" className="text-sm font-semibold text-fg">
                  Sources ({cluster.sources.length})
                </h3>
                <ul className="mt-3 flex flex-col gap-3">
                  {cluster.sources.map((source) => (
                    <li key={source.url} className="rounded-lg border border-border p-3">
                      <p className="text-sm font-medium text-fg">{source.publisher}</p>
                      {source.title !== null && source.title !== '' ? (
                        <p className="mt-1 text-sm text-muted-fg">{source.title}</p>
                      ) : null}
                      <a
                        href={source.url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="mt-2 inline-flex min-h-11 items-center text-xs text-primary underline-offset-4 hover:underline"
                      >
                        {sourceHost(source.url)}
                      </a>
                      {source.published_at !== null ? (
                        <span className="ml-3 text-xs text-muted-fg">
                          {relativeTime(source.published_at)}
                        </span>
                      ) : null}
                    </li>
                  ))}
                  {cluster.sources.length === 0 ? (
                    <li className="text-sm text-muted-fg">No source links are stored.</li>
                  ) : null}
                </ul>
              </section>

              <section aria-labelledby="cluster-siblings">
                <h3 id="cluster-siblings" className="text-sm font-semibold text-fg">
                  Siblings ({cluster.siblings.length})
                </h3>
                <ul className="mt-3 flex flex-col gap-3">
                  {cluster.siblings.map((sibling) => (
                    <li key={sibling.id} className="rounded-lg border border-border p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">{sibling.category}</Badge>
                        {sibling.hidden ? <Badge variant="flat">hidden</Badge> : null}
                        {sibling.pinned ? <Badge variant="bull">pinned</Badge> : null}
                        <span className="text-xs text-muted-fg tabular-nums">
                          score {sibling.importance_score}
                        </span>
                      </div>
                      <p className="mt-2 text-sm text-fg">{sibling.headline}</p>
                      <p className="mt-1 text-xs text-muted-fg">
                        {relativeTime(sibling.published_at)}
                      </p>
                    </li>
                  ))}
                  {cluster.siblings.length === 0 ? (
                    <li className="text-sm text-muted-fg">
                      Nothing else merged into this cluster.
                    </li>
                  ) : null}
                </ul>
              </section>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
