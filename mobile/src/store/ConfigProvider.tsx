/**
 * /api/config, fetched once after the handshake and shared by every screen.
 *
 * The server owns which categories and market filters exist and whether the app
 * is in maintenance (CONTRACT_MOBILE_ADMIN.md sections 6.2 and 6.6), so a tab
 * bar built from a local constant would keep showing a category the admin turned
 * off an hour ago. Screens read the lists from here instead.
 *
 * Two deliberate choices:
 *
 *   - A failed config call is not fatal. The app falls back to the category and
 *     filter lists in @finbit/shared, which are the same values the server ships
 *     by default, so the feed still works on a flaky connection. The error is
 *     exposed for a screen that wants to mention it.
 *   - The 'all' pseudo-category is guaranteed to be first in `categories` even if
 *     the payload omits it, because it is a UI concept the server does not store
 *     (CONTRACT.md section 4). Feed code can render the list as it comes.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from 'react';

import { api, describeError } from '@/src/api/client';
import {
  CATEGORIES,
  MARKET_FILTERS,
  type ConfigCategory,
  type ConfigMarketFilter,
  type PublicConfig,
  type SortMode,
} from '@/src/lib/types';

/** Used until the first call returns, and after one that failed. */
const FALLBACK_CATEGORIES: ConfigCategory[] = CATEGORIES.map((entry) => ({
  key: entry.key,
  label: entry.label,
  enabled: true,
}));

const FALLBACK_MARKET_FILTERS: ConfigMarketFilter[] = MARKET_FILTERS.map((entry) => ({
  key: entry.key,
  label: entry.label,
  enabled: true,
}));

const ALL_CATEGORY: ConfigCategory = { key: 'all', label: 'All', enabled: true };

export interface ConfigState {
  /** The raw payload, or null before the first successful call. */
  config: PublicConfig | null;
  /** Enabled categories only, 'all' first. Safe to render directly as tabs. */
  categories: ConfigCategory[];
  /** Enabled market filters only, in server order. */
  marketFilters: ConfigMarketFilter[];
  /** The sort the feed opens with. */
  defaultSort: SortMode;
  /** True while the admin has the app switched off. Render the message, not a feed. */
  maintenance: boolean;
  maintenanceMessage: string | null;
  /** A semver string to compare against the build, or null when unset. */
  minMobileVersion: string | null;
  /** True during the first load only, so a refresh does not blank the tabs. */
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

const DEFAULT_MAINTENANCE_MESSAGE =
  'FinBit is briefly down for maintenance. Please check back shortly.';

const ConfigContext = createContext<ConfigState | null>(null);

function enabledCategories(config: PublicConfig | null): ConfigCategory[] {
  const source = config === null ? FALLBACK_CATEGORIES : config.categories;
  const enabled = source.filter((entry) => entry.enabled);
  return enabled.some((entry) => entry.key === 'all') ? enabled : [ALL_CATEGORY, ...enabled];
}

function enabledMarketFilters(config: PublicConfig | null): ConfigMarketFilter[] {
  const source = config === null ? FALLBACK_MARKET_FILTERS : config.market_filters;
  return source.filter((entry) => entry.enabled);
}

export function ConfigProvider({ children }: { children: ReactNode }): ReactElement {
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    try {
      const next = await api.config();
      if (mounted.current) {
        setConfig(next);
        setError(null);
      }
    } catch (caught) {
      if (mounted.current) {
        setError(describeError(caught));
      }
    } finally {
      if (mounted.current) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo<ConfigState>(() => {
    const maintenance = config?.maintenance_mode ?? false;
    return {
      config,
      categories: enabledCategories(config),
      marketFilters: enabledMarketFilters(config),
      defaultSort: config?.default_sort ?? 'top',
      maintenance,
      maintenanceMessage: maintenance
        ? (config?.maintenance_message ?? DEFAULT_MAINTENANCE_MESSAGE)
        : null,
      minMobileVersion: config?.min_mobile_version ?? null,
      loading,
      error,
      refresh,
    };
  }, [config, loading, error, refresh]);

  return <ConfigContext.Provider value={value}>{children}</ConfigContext.Provider>;
}

export function useConfig(): ConfigState {
  const value = useContext(ConfigContext);
  if (value === null) {
    throw new Error('useConfig must be used inside ConfigProvider.');
  }
  return value;
}
