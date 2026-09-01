/**
 * Maintenance mode: context, provider, hook and the banner itself.
 *
 * Maintenance mode is edited on the Flags screen but has to be visible from
 * every screen, because while it is on every device-authenticated content route
 * answers 503 and both apps are showing a stop screen. An admin who forgets
 * that has taken the product down, so contract section 9 asks for a banner that
 * never goes away while the flag is on.
 *
 * The provider reads the flag itself rather than being fed by the Flags screen,
 * so the banner is correct on a cold load of the Content screen too. A save on
 * the Flags screen then calls apply(), which updates the banner from the value
 * the API just confirmed instead of paying for a second round trip.
 *
 * A failed read is deliberately silent. Not knowing whether maintenance is on
 * is not worth a toast on top of whatever error the screen itself is showing,
 * and the screens all surface their own failures.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { TriangleAlert } from 'lucide-react';

import { adminApi } from '../api';

export interface MaintenanceState {
  enabled: boolean;
  message: string | null;
  /** Adopt the value a successful flags save just wrote. */
  apply: (enabled: boolean, message: string | null) => void;
  /** Re-read the flag from the API. */
  refresh: () => Promise<void>;
}

const MaintenanceContext = createContext<MaintenanceState | null>(null);

export function MaintenanceProvider({ children }: { children: ReactNode }): JSX.Element {
  const [enabled, setEnabled] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal): Promise<void> => {
    try {
      const flags = await adminApi.getFlags(signal);
      setEnabled(flags.maintenance_mode);
      setMessage(flags.maintenance_message);
    } catch {
      // Leave the banner as it is: the screens report their own failures.
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => {
      controller.abort();
    };
  }, [load]);

  const apply = useCallback((next: boolean, nextMessage: string | null) => {
    setEnabled(next);
    setMessage(nextMessage);
  }, []);

  const refresh = useCallback(() => load(), [load]);

  const value = useMemo<MaintenanceState>(
    () => ({ enabled, message, apply, refresh }),
    [enabled, message, apply, refresh],
  );

  return <MaintenanceContext.Provider value={value}>{children}</MaintenanceContext.Provider>;
}

/** Reads maintenance mode. Throws outside the provider, which is a bug. */
export function useMaintenance(): MaintenanceState {
  const value = useContext(MaintenanceContext);
  if (value === null) {
    throw new Error('useMaintenance must be used inside MaintenanceProvider.');
  }
  return value;
}

const DEFAULT_MAINTENANCE_MESSAGE = 'FinBit is in maintenance mode. No message has been set.';

/**
 * The persistent banner. Renders nothing at all while the flag is off, so it
 * costs no vertical space in the normal case.
 */
export function MaintenanceBanner(): JSX.Element | null {
  const { enabled, message } = useMaintenance();

  if (!enabled) {
    return null;
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-start gap-3 bg-breaking px-4 py-3 text-on-breaking"
    >
      <TriangleAlert aria-hidden="true" className="mt-0.5 size-5 shrink-0" />
      <p className="text-sm font-medium">
        <span className="font-semibold">Maintenance mode is on.</span>{' '}
        {message !== null && message !== '' ? message : DEFAULT_MAINTENANCE_MESSAGE}{' '}
        <span className="font-normal opacity-90">
          The mobile and web apps are showing this message instead of the feed.
        </span>
      </p>
    </div>
  );
}
