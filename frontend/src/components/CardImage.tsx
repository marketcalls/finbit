/**
 * The lead image on a story card, contract section 14.5.
 *
 * Three things matter here and they are all about the image never being
 * allowed to disturb the card around it.
 *
 * 1. Space is reserved before the pixels arrive. The box is a fixed 16 by 9
 *    ratio in full mode and a fixed 72 px square in compact mode, so the feed,
 *    which is a mandatory scroll-snap column, never reflows when a late image
 *    decodes. Cumulative layout shift from images is zero by construction.
 * 2. The image is decorative in the accessibility sense. The headline sits
 *    directly beside it and carries the meaning, so alt is always empty and the
 *    whole box is hidden from assistive technology. Descriptive alt would be a
 *    guess about a picture nobody here has seen, and repeating the headline
 *    would make a screen reader say it twice.
 * 3. A missing or broken image degrades into a typographic plate, never into a
 *    browser broken-image icon: the muted token, the category label and up to
 *    two tickers in tabular figures, tinted by the impact direction token.
 *
 * The image is hotlinked from the publisher CDN (contract section 14), so
 * failures are expected in normal use: an expired URL, a hotlink block, a
 * network drop. Failure is tracked per source URL, and once a URL has failed
 * the img element is not rendered again for it, so an onError loop is not
 * possible.
 *
 * The box is never a link and never a button. The existing card controls stay
 * the only interactive elements.
 */

import { useCallback, useState } from 'react';
import type { ImpactDirection } from '../api/types';
import { CATEGORY_LABELS } from './CategoryTabs';

/** Contract section 14.5: the fallback plate shows at most two symbols. */
const MAX_FALLBACK_SYMBOLS = 2;

/** Semantic mapping from contract section 10. "mixed" never gets a new hue. */
const TEXT_TINT: Record<ImpactDirection, string> = {
  bullish: 'text-bull',
  bearish: 'text-bear',
  neutral: 'text-flat',
  mixed: 'text-fg',
};

const RULE_TINT: Record<Exclude<ImpactDirection, 'mixed'>, string> = {
  bullish: 'bg-bull',
  bearish: 'bg-bear',
  neutral: 'bg-flat',
};

/**
 * Only an absolute http or https URL is usable. The backend already filters
 * these out, so this is a cheap guard against a bad row rather than a policy.
 */
function usableSrc(src: string | null): string | null {
  if (typeof src !== 'string') {
    return null;
  }
  const trimmed = src.trim();
  const lower = trimmed.toLowerCase();
  if (!lower.startsWith('http://') && !lower.startsWith('https://')) {
    return null;
  }
  return trimmed;
}

/** The display label for a category key, with the raw key as a last resort. */
function categoryLabel(category: string): string {
  const known: Partial<Record<string, string>> = CATEGORY_LABELS;
  const label = known[category];
  if (label) {
    return label;
  }
  return category.trim() === '' ? 'Markets' : category.trim().toUpperCase();
}

/** First occurrences only, blanks dropped, capped at two. */
function fallbackSymbols(symbols: string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of symbols) {
    if (typeof raw !== 'string') {
      continue;
    }
    const symbol = raw.trim();
    if (symbol === '' || seen.has(symbol)) {
      continue;
    }
    seen.add(symbol);
    out.push(symbol);
    if (out.length === MAX_FALLBACK_SYMBOLS) {
      break;
    }
  }
  return out;
}

/**
 * A short rule under the plate carrying the direction as colour. "mixed" is a
 * split bull and bear rule, matching the split chip in ImpactBadge, so no
 * fourth hue is invented. Colour is never the only carrier here: the rule is
 * decoration under a card that already states the direction in words.
 */
function DirectionRule({ direction }: { direction: ImpactDirection }): JSX.Element {
  if (direction === 'mixed') {
    return (
      <span className="mt-3 flex h-0.5 w-10 overflow-hidden rounded-full">
        <span className="h-full flex-1 bg-bull" />
        <span className="h-full flex-1 bg-bear" />
      </span>
    );
  }
  return <span className={`mt-3 block h-0.5 w-10 rounded-full ${RULE_TINT[direction]}`} />;
}

export interface CardImageProps {
  /** ArticleCard.image_url. Null means no image was resolved for this story. */
  src: string | null;
  /** ArticleCard.category, used for the label on the fallback plate. */
  category: string;
  /** ArticleCard.symbols mapped to plain tickers. At most two are shown. */
  symbols: string[];
  /** ArticleCard.impact_direction, which tints the fallback plate. */
  direction: ImpactDirection;
  /** Search and Saved use compact: a 72 px leading thumbnail, not a banner. */
  compact?: boolean;
}

export function CardImage({
  src,
  category,
  symbols,
  direction,
  compact = false,
}: CardImageProps): JSX.Element {
  /*
    Both pieces of state are keyed by the URL they describe rather than being
    plain booleans, so a card that is recycled onto a different story resets
    itself during render with no effect and no flash of the previous image.
  */
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const [readySrc, setReadySrc] = useState<string | null>(null);

  const url = usableSrc(src);
  const broken = url === null || failedSrc === url;
  const ready = url !== null && readySrc === url;

  const onError = useCallback(() => {
    setFailedSrc(url);
  }, [url]);

  const onLoad = useCallback(() => {
    setReadySrc(url);
  }, [url]);

  /*
    A cached image can finish before React attaches its handlers, in which case
    neither load nor error ever fires. Settle that case from the element itself
    the moment the ref lands: complete with no intrinsic width means it failed.
  */
  const attach = useCallback(
    (node: HTMLImageElement | null) => {
      if (node === null || url === null || !node.complete) {
        return;
      }
      if (node.naturalWidth > 0) {
        setReadySrc(url);
      } else {
        setFailedSrc(url);
      }
    },
    [url],
  );

  const box = compact
    ? 'relative h-[72px] w-[72px] shrink-0 overflow-hidden rounded-md border border-border bg-muted'
    : 'relative aspect-video w-full shrink-0 overflow-hidden rounded-lg border border-border bg-muted';

  const shown = broken ? fallbackSymbols(symbols) : [];
  const tint = TEXT_TINT[direction] ?? TEXT_TINT.neutral;
  const label = categoryLabel(category);

  return (
    /*
      Hidden from assistive technology on purpose. The image is decorative, and
      the fallback plate only repeats the category and the tickers, both of
      which the card already states in text further down.
    */
    <div aria-hidden="true" className={box}>
      {broken ? (
        <div
          className={`flex h-full w-full flex-col items-center justify-center text-center ${
            compact ? 'gap-0.5 px-1' : 'px-4'
          }`}
        >
          {shown.length > 0 ? (
            <>
              <span
                className={`max-w-full truncate font-semibold uppercase text-muted-fg ${
                  compact ? 'w-full text-[9px] tracking-[0.1em]' : 'text-[11px] tracking-[0.14em]'
                }`}
              >
                {label}
              </span>
              <span
                className={`flex w-full flex-col items-center font-semibold leading-tight tnum ${tint} ${
                  compact ? '' : 'mt-2 gap-0.5'
                }`}
              >
                {shown.map((symbol) => (
                  <span
                    key={symbol}
                    className={`block max-w-full truncate ${
                      compact ? 'text-[11px]' : 'text-2xl sm:text-3xl'
                    }`}
                  >
                    {symbol}
                  </span>
                ))}
              </span>
            </>
          ) : (
            <span
              className={`max-w-full truncate font-headline font-semibold ${tint} ${
                compact ? 'w-full text-[11px]' : 'text-xl sm:text-2xl'
              }`}
            >
              {label}
            </span>
          )}

          {compact ? null : <DirectionRule direction={direction} />}
        </div>
      ) : (
        /*
          The muted box behind this img is the placeholder, so there is no
          spinner: an empty tinted rectangle is quieter than a spinner that
          fires on every card in a scroll feed. The image fades in on load,
          opacity only, and the global reduced-motion rule removes even that.
        */
        <img
          ref={attach}
          src={url}
          alt=""
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          draggable={false}
          onLoad={onLoad}
          onError={onError}
          className={`absolute inset-0 h-full w-full object-cover transition-opacity duration-200 ${
            ready ? 'opacity-100' : 'opacity-0'
          }`}
        />
      )}
    </div>
  );
}
