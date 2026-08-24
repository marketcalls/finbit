/**
 * Ticker chips for a story, contract sections 4 and 11.
 *
 * At most `max` chips are shown (default 6) followed by a "+N" overflow
 * indicator. A chip is a real button when onSelect is supplied, so it can drive
 * the feed symbol filter or a search, and a plain span otherwise. The chips are
 * visually compact, so each button carries an invisible 44 px tall hit area
 * through an ::after pseudo element rather than growing the chip itself.
 */

import type { SymbolTag } from '../api/types';

const DEFAULT_MAX = 6;

const CHIP_BASE =
  'relative inline-flex items-center rounded-md border border-border bg-muted px-2 py-1 text-xs font-medium tracking-wide text-fg tnum';

const CHIP_BUTTON =
  'transition-colors duration-150 hover:border-accent hover:bg-card hover:text-fg ' +
  "after:absolute after:inset-x-0 after:top-1/2 after:h-11 after:-translate-y-1/2 after:content-['']";

/** Human wording for the exchange, used in the accessible name of a chip. */
function describeTag(tag: SymbolTag): string {
  switch (tag.exchange) {
    case 'INDEX':
      return `${tag.symbol}, index`;
    case 'COMMODITY':
      return `${tag.symbol}, commodity`;
    case 'FX':
      return `${tag.symbol}, currency pair`;
    case 'CRYPTO':
      return `${tag.symbol}, crypto`;
    default:
      return `${tag.symbol} on ${tag.exchange}`;
  }
}

export interface SymbolChipsProps {
  symbols: SymbolTag[];
  onSelect?: (symbol: string) => void;
  /** Default 6. */
  max?: number;
}

export function SymbolChips({ symbols, onSelect, max = DEFAULT_MAX }: SymbolChipsProps): JSX.Element {
  const limit = Number.isFinite(max) && max > 0 ? Math.floor(max) : DEFAULT_MAX;

  // The API can repeat a symbol across merged sources, so keep first occurrences.
  const unique: SymbolTag[] = [];
  const seen = new Set<string>();
  for (const tag of symbols) {
    if (!tag || typeof tag.symbol !== 'string' || tag.symbol === '' || seen.has(tag.symbol)) {
      continue;
    }
    seen.add(tag.symbol);
    unique.push(tag);
  }

  if (unique.length === 0) {
    return <></>;
  }

  const shown = unique.slice(0, limit);
  const overflow = unique.length - shown.length;

  /*
    The row gap is wider than the column gap on purpose: the invisible 44 px hit
    area reaches about 9 px above and below a chip, so a tighter row gap would
    let one row's hit area sit on top of the row above it.
  */
  return (
    <ul aria-label="Symbols in this story" className="flex flex-wrap items-center gap-x-1.5 gap-y-2.5">
      {shown.map((tag) => (
        <li key={tag.symbol}>
          {onSelect ? (
            <button
              type="button"
              onClick={() => onSelect(tag.symbol)}
              aria-label={`Filter by ${describeTag(tag)}`}
              title={describeTag(tag)}
              className={`${CHIP_BASE} ${CHIP_BUTTON}`}
            >
              {tag.symbol}
            </button>
          ) : (
            <span title={describeTag(tag)} className={CHIP_BASE}>
              {tag.symbol}
            </span>
          )}
        </li>
      ))}

      {overflow > 0 ? (
        <li>
          <span className={`${CHIP_BASE} text-muted-fg`}>
            <span aria-hidden="true">+{overflow}</span>
            <span className="sr-only">
              and {overflow} more {overflow === 1 ? 'symbol' : 'symbols'}
            </span>
          </span>
        </li>
      ) : null}
    </ul>
  );
}
