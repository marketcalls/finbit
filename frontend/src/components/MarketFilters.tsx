/**
 * Market quick filter chips, contract sections 4, 10 and 11.
 *
 * These filter the feed by symbol rather than by category. Each chip is a
 * toggle: pressing the active chip clears the filter. When a symbol picked from
 * a card is not one of the six standard filters, it is shown as an extra chip
 * so it can always be cleared from here.
 */

import type { MarketFilterInfo } from '../api/types';

/** Used until GET /api/categories answers, and whenever that call fails. */
export const DEFAULT_MARKET_FILTERS: MarketFilterInfo[] = [
  { key: 'NIFTY', label: 'Nifty' },
  { key: 'BANKNIFTY', label: 'Bank Nifty' },
  { key: 'SENSEX', label: 'Sensex' },
  { key: 'USDINR', label: 'USDINR' },
  { key: 'GOLD', label: 'Gold' },
  { key: 'CRUDE', label: 'Crude' },
];

interface Chip {
  key: string;
  label: string;
}

export interface MarketFiltersProps {
  filters: MarketFilterInfo[];
  /** The symbol the feed is filtered by, or null for no symbol filter. */
  active: string | null;
  /** Called with the chip symbol. The caller decides to set or clear. */
  onToggle: (symbol: string) => void;
}

export function MarketFilters({ filters, active, onToggle }: MarketFiltersProps): JSX.Element {
  const chips: Chip[] = filters.map((filter) => ({ key: filter.key, label: filter.label }));

  // A symbol chosen from a card, for example RELIANCE, is not in the standard
  // six, so surface it first and keep it clearable.
  if (active && !chips.some((chip) => chip.key === active)) {
    chips.unshift({ key: active, label: active });
  }

  return (
    <div
      role="group"
      aria-label="Market filters"
      className="no-scrollbar flex w-full items-center gap-2 overflow-x-auto"
    >
      {chips.map((chip) => {
        const pressed = chip.key === active;
        return (
          <button
            key={chip.key}
            type="button"
            aria-pressed={pressed}
            onClick={() => onToggle(chip.key)}
            className={`inline-flex min-h-11 shrink-0 items-center rounded-full border px-3.5 text-xs font-semibold tracking-wide whitespace-nowrap transition-colors duration-150 ${
              pressed
                ? 'border-fg bg-fg text-bg'
                : 'border-border text-muted-fg hover:border-muted-fg hover:text-fg'
            }`}
          >
            {chip.label}
          </button>
        );
      })}
    </div>
  );
}
