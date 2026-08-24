/**
 * The FinBit story card, contract sections 10 and 11.
 *
 * Order of contents, top to bottom: an optional breaking flag, the lead image,
 * the headline in Newsreader, the 50 to 80 word summary, a Why it matters block
 * when the API sent one, symbol chips, the Market Impact row, a meta line, and
 * a footer with the sources button and the bookmark toggle.
 *
 * In compact mode the image becomes a 72 px leading thumbnail with the headline
 * and summary beside it, which is the shape Search and Saved results want.
 * Everything below that row is unchanged and stays full width.
 *
 * The card itself is not a link or a button. Only the individual controls are
 * interactive. The image is never interactive at all, see CardImage.
 */

import { useCallback, useId, useState } from 'react';
import type { ArticleCard } from '../api/types';
import { useBookmarks } from '../lib/bookmarks';
import { absoluteTime, relativeTime } from '../lib/format';
import { CardImage } from './CardImage';
import { CATEGORY_LABELS } from './CategoryTabs';
import { IconAlert, IconBookmark, IconBookmarkFilled, IconChevronRight } from './Icons';
import { ImpactBadge } from './ImpactBadge';
import { ImpactMap } from './ImpactMap';
import { SourcesSheet } from './SourcesSheet';
import { SymbolChips } from './SymbolChips';

const LABEL = 'text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-fg';

function Dot(): JSX.Element {
  return (
    <span
      aria-hidden="true"
      className="inline-block h-1 w-1 shrink-0 rounded-full bg-muted-fg align-middle"
    />
  );
}

export interface NewsCardProps {
  article: ArticleCard;
  /** Search and Saved use compact: no snap sizing and tighter spacing. */
  compact?: boolean;
  /** Called when a symbol chip is chosen, so the caller can filter by it. */
  onSelectSymbol?: (symbol: string) => void;
}

export function NewsCard({ article, compact = false, onSelectSymbol }: NewsCardProps): JSX.Element {
  const { isSaved, toggle, loading } = useBookmarks();
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const headlineId = `${useId()}-headline`;

  // The provider is the shared source of truth. While it is still loading its
  // first list, fall back to what the feed payload reported.
  const saved = loading ? article.bookmarked : isSaved(article.id);
  const sourceCount = article.sources.length;
  const published = article.published_at;

  const onToggleBookmark = useCallback(async () => {
    if (busy) {
      return;
    }
    setBusy(true);
    try {
      await toggle(article.id);
    } finally {
      setBusy(false);
    }
  }, [article.id, busy, toggle]);

  const shell = compact
    ? 'flex w-full flex-col gap-2.5 rounded-xl border border-border bg-card px-4 py-4'
    : 'feed-snap flex w-full flex-1 flex-col gap-4 border-b border-border bg-card px-5 py-6 md:border-x';

  /*
    The image, the headline and the summary are built once and then arranged
    two ways: stacked in full mode, and as a thumbnail row in compact mode.
    The row needs min-w-0 on the text column, otherwise the flex default of
    min-width:auto lets a long headline push the layout wider than the card.
  */
  const image = (
    <CardImage
      src={article.image_url}
      category={article.category}
      symbols={article.symbols.map((tag) => tag.symbol)}
      direction={article.impact_direction}
      compact={compact}
    />
  );

  const headline = (
    <h2
      id={headlineId}
      className={`font-headline font-semibold tracking-tight text-fg ${
        compact ? 'text-lg leading-snug' : 'text-2xl leading-[1.18] sm:text-[1.75rem]'
      }`}
    >
      {article.headline}
    </h2>
  );

  const summary = (
    <p
      className={`text-muted-fg ${
        compact ? 'line-clamp-3 text-sm leading-relaxed' : 'text-[0.975rem] leading-[1.65]'
      }`}
    >
      {article.summary}
    </p>
  );

  return (
    <article className={shell} aria-labelledby={headlineId}>
      {article.is_breaking ? (
        <p className="inline-flex w-fit items-center gap-1.5 rounded-sm bg-breaking px-2 py-1 text-[11px] font-bold uppercase tracking-[0.14em] text-on-breaking">
          <IconAlert className="h-3.5 w-3.5" />
          Breaking
        </p>
      ) : null}

      {compact ? (
        <div className="flex items-start gap-3">
          {image}
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            {headline}
            {summary}
          </div>
        </div>
      ) : (
        <>
          {image}
          {headline}
          {summary}
        </>
      )}

      {article.why_it_matters ? (
        <div className="rounded-md border-l-2 border-accent bg-muted px-3 py-2.5">
          <p className={LABEL}>Why it matters</p>
          <p className="mt-1 text-sm leading-relaxed text-fg">{article.why_it_matters}</p>
        </div>
      ) : null}

      {article.symbols.length > 0 ? (
        <SymbolChips symbols={article.symbols} onSelect={onSelectSymbol} max={compact ? 4 : 6} />
      ) : null}

      <section aria-label="Market Impact" className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h3 className={`font-sans ${LABEL}`}>Market Impact</h3>
          <ImpactBadge impact={article.impact} direction={article.impact_direction} />
        </div>
        {!compact && article.impact_map.length > 0 ? (
          <ImpactMap entries={article.impact_map} />
        ) : null}
      </section>

      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-fg">
        <time className="tnum" dateTime={published} title={absoluteTime(published)}>
          {relativeTime(published)}
        </time>
        <Dot />
        <span>{CATEGORY_LABELS[article.category]}</span>
        {!compact && article.topics.length > 0 ? (
          <>
            <Dot />
            <span>{article.topics.slice(0, 2).join(', ')}</span>
          </>
        ) : null}
      </p>

      <footer
        className={`flex items-center justify-between gap-3 border-t border-border ${
          compact ? 'pt-2' : 'mt-auto pt-3'
        }`}
      >
        {sourceCount > 0 ? (
          <button
            type="button"
            onClick={() => setSourcesOpen(true)}
            className="-ml-2 inline-flex min-h-11 items-center gap-1 rounded-md px-2 text-sm font-medium text-fg transition-colors duration-150 hover:bg-muted"
          >
            <span>
              Sources <span className="tnum">({sourceCount})</span>
            </span>
            <IconChevronRight className="h-4 w-4 text-muted-fg" />
          </button>
        ) : (
          <p className="text-xs text-muted-fg">
            <span className="tnum">{article.source_count}</span> reported sources
          </p>
        )}

        <button
          type="button"
          onClick={onToggleBookmark}
          aria-pressed={saved}
          aria-label={saved ? 'Remove this story from saved' : 'Save this story'}
          title={saved ? 'Remove this story from saved' : 'Save this story'}
          className="-mr-2 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-muted-fg transition-colors duration-150 hover:bg-muted hover:text-fg"
        >
          {saved ? (
            <IconBookmarkFilled className="h-5 w-5 text-fg" />
          ) : (
            <IconBookmark className="h-5 w-5" />
          )}
        </button>
      </footer>

      <SourcesSheet
        open={sourcesOpen}
        onClose={() => setSourcesOpen(false)}
        headline={article.headline}
        sources={article.sources}
      />
    </article>
  );
}
