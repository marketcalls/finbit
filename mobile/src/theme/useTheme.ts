/**
 * Theme state: follow the system, or override it from Settings.
 *
 * Three preferences ('system', 'light', 'dark') resolve to two schemes. Keeping
 * the preference and the resolved scheme apart is what lets Settings show
 * "System" as a real choice instead of guessing which of the two the user meant,
 * and it is why a phone switching to dark at sunset moves the app with it unless
 * the user has explicitly pinned one.
 *
 * The preference lives in AsyncStorage. It is not a credential, so it does not
 * belong in SecureStore (CONTRACT_MOBILE_ADMIN.md section 8.3), and the key
 * matches the web app's so the two read the same in a shared codebase.
 *
 * This file has no JSX so it can stay a .ts module alongside the other theme
 * files; the provider is three createElement calls and reads no worse for it.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactElement,
  type ReactNode,
} from 'react';
import { useColorScheme } from 'react-native';

import {
  themeTokens,
  type ColorScheme,
  type ColorTokens,
  type ThemeTokens,
} from './tokens';

/** What the user chose. 'system' means "whatever the phone is doing". */
export type ThemePreference = 'system' | 'light' | 'dark';

export const THEME_STORAGE_KEY = 'finbit.theme';

/** The scheme used before the phone reports one, matching the web app's default. */
const FALLBACK_SCHEME: ColorScheme = 'dark';

export interface ThemeState extends ThemeTokens {
  /** The stored choice, which is what the Settings screen renders as selected. */
  preference: ThemePreference;
  /** Persists the choice and repaints. Failing to write is not fatal. */
  setPreference: (next: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeState | null>(null);

function isPreference(value: unknown): value is ThemePreference {
  return value === 'system' || value === 'light' || value === 'dark';
}

/**
 * Reads the stored preference before the first paint, then keeps the resolved
 * scheme in step with the phone while the preference is 'system'.
 *
 * Children are held back for the one storage read. It resolves in a few
 * milliseconds behind the native splash, which is cheaper than painting the
 * wrong palette and flipping it a frame later.
 */
export function ThemeProvider(props: { children: ReactNode }): ReactElement | null {
  const systemScheme = useColorScheme();
  const [preference, setPreferenceState] = useState<ThemePreference>('system');
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const stored = await AsyncStorage.getItem(THEME_STORAGE_KEY);
        if (!cancelled && isPreference(stored)) {
          setPreferenceState(stored);
        }
      } catch {
        // Storage is unavailable on this device. The system theme is a fine
        // answer and the choice simply will not survive a restart.
      } finally {
        if (!cancelled) {
          setLoaded(true);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    void AsyncStorage.setItem(THEME_STORAGE_KEY, next).catch(() => {
      // Same as above: the app still repaints, the choice is just not persisted.
    });
  }, []);

  const scheme: ColorScheme =
    preference === 'system' ? (systemScheme ?? FALLBACK_SCHEME) : preference;

  const value = useMemo<ThemeState>(
    () => ({ ...themeTokens(scheme), preference, setPreference }),
    [scheme, preference, setPreference],
  );

  if (!loaded) {
    return null;
  }

  return createElement(ThemeContext.Provider, { value }, props.children);
}

/** The full token set plus the preference controls. */
export function useTheme(): ThemeState {
  const value = useContext(ThemeContext);
  if (value === null) {
    throw new Error('useTheme must be used inside ThemeProvider.');
  }
  return value;
}

/** Just the palette, which is what most components need. */
export function useThemeColors(): ColorTokens {
  return useTheme().colors;
}
