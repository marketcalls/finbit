/**
 * Category tablist for the feed, contract sections 4, 10 and 11.
 *
 * A horizontally scrollable ARIA tablist with roving tabindex: only the
 * selected tab is in the tab order, and the arrow keys, Home and End move
 * focus and selection between tabs.
 */

import { useCallback, useEffect, useRef } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';
import type { CategoryInfo, CategoryKey } from '../api/types';
import { compactNumber } from '../lib/format';

/** Display order from contract section 4. "all" is the UI-only pseudo category. */
export const CATEGORY_ORDER: readonly CategoryKey[] = [
  'all',
  'india',
  'global',
  'stocks',
  'economy',
  'rbi',
  'sebi',
  'earnings',
  'commodities',
  'crypto',
];

/** Display labels from contract section 4, shared with NewsCard. */
export const CATEGORY_LABELS: Record<CategoryKey, string> = {
  all: 'All',
  india: 'India',
  global: 'Global',
  stocks: 'Stocks',
  economy: 'Economy',
  rbi: 'RBI',
  sebi: 'SEBI',
  earnings: 'Earnings',
  commodities: 'Commodities',
  crypto: 'Crypto',
};

/** Used until GET /api/categories answers, and whenever that call fails. */
export const DEFAULT_CATEGORIES: CategoryInfo[] = CATEGORY_ORDER.map((key) => ({
  key,
  label: CATEGORY_LABELS[key],
  count: 0,
}));

/** The id of the tab button for a category, so a panel can point back at it. */
export function categoryTabId(key: CategoryKey): string {
  return `feed-tab-${key}`;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

export interface CategoryTabsProps {
  /** Tabs in display order. Counts of 0 are hidden. */
  categories: CategoryInfo[];
  active: CategoryKey;
  onChange: (key: CategoryKey) => void;
  /** Id of the element the tabs control, used for aria-controls. */
  panelId: string;
}

export function CategoryTabs({
  categories,
  active,
  onChange,
  panelId,
}: CategoryTabsProps): JSX.Element {
  const tabRefs = useRef(new Map<CategoryKey, HTMLButtonElement>());

  const registerTab = useCallback((key: CategoryKey, node: HTMLButtonElement | null) => {
    if (node) {
      tabRefs.current.set(key, node);
    } else {
      tabRefs.current.delete(key);
    }
  }, []);

  // Keep the selected tab visible when the rail is scrolled or the list grows.
  useEffect(() => {
    const node = tabRefs.current.get(active);
    node?.scrollIntoView({
      behavior: prefersReducedMotion() ? 'auto' : 'smooth',
      block: 'nearest',
      inline: 'center',
    });
  }, [active, categories]);

  const focusTab = useCallback((key: CategoryKey) => {
    const node = tabRefs.current.get(key);
    node?.focus();
  }, []);

  const handleKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
      if (categories.length === 0 || event.ctrlKey || event.metaKey || event.altKey) {
        return;
      }

      let nextIndex: number;
      switch (event.key) {
        case 'ArrowRight':
          nextIndex = (index + 1) % categories.length;
          break;
        case 'ArrowLeft':
          nextIndex = (index - 1 + categories.length) % categories.length;
          break;
        case 'Home':
          nextIndex = 0;
          break;
        case 'End':
          nextIndex = categories.length - 1;
          break;
        default:
          return;
      }

      // Stops the feed keyboard shortcuts in FeedScreen from also reacting.
      event.preventDefault();
      const next = categories[nextIndex];
      onChange(next.key);
      focusTab(next.key);
    },
    [categories, focusTab, onChange],
  );

  return (
    <div
      role="tablist"
      aria-label="News categories"
      aria-orientation="horizontal"
      className="no-scrollbar flex w-full items-stretch gap-1 overflow-x-auto px-2"
    >
      {categories.map((item, index) => {
        const selected = item.key === active;
        return (
          <button
            key={item.key}
            id={categoryTabId(item.key)}
            ref={(node) => {
              registerTab(item.key, node);
            }}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={panelId}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(item.key)}
            onKeyDown={(event) => handleKeyDown(event, index)}
            className={`inline-flex min-h-11 shrink-0 items-center gap-1.5 border-b-2 px-3 text-sm font-medium whitespace-nowrap transition-colors duration-150 ${
              selected
                ? 'border-fg text-fg'
                : 'border-transparent text-muted-fg hover:text-fg'
            }`}
          >
            <span>{item.label}</span>
            {item.count > 0 ? (
              <span className="tnum text-[11px] leading-none text-muted-fg">
                {compactNumber(item.count)}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
