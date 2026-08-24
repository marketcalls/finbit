/**
 * Theme state, contract section 10. Dark is the default. The chosen theme is
 * stored in localStorage under finbit.theme and mirrored onto the html element
 * as data-theme, which is what index.css switches on.
 *
 * The inline script in index.html already applies the right theme before first
 * paint. This module keeps React, the DOM and storage in agreement afterwards.
 */

import { useCallback, useSyncExternalStore } from 'react';

export type Theme = 'dark' | 'light';

export const THEME_STORAGE_KEY = 'finbit.theme';

const hasDom = typeof document !== 'undefined';

const listeners = new Set<() => void>();

function readStoredTheme(): Theme | null {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return stored === 'dark' || stored === 'light' ? stored : null;
  } catch {
    return null;
  }
}

function writeStoredTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Storage is blocked, so the choice lasts for this session only.
  }
}

function systemTheme(): Theme {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return 'dark';
  }
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function resolveInitialTheme(): Theme {
  const stored = readStoredTheme();
  if (stored) {
    return stored;
  }
  if (hasDom) {
    const attribute = document.documentElement.getAttribute('data-theme');
    if (attribute === 'dark' || attribute === 'light') {
      return attribute;
    }
  }
  return systemTheme();
}

function applyTheme(theme: Theme): void {
  if (!hasDom) {
    return;
  }
  const root = document.documentElement;
  root.setAttribute('data-theme', theme);
  root.style.colorScheme = theme;

  // Keep the browser chrome colour in step, reading the token rather than a literal.
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    const background = getComputedStyle(root).getPropertyValue('--bg').trim();
    if (background !== '') {
      meta.setAttribute('content', background);
    }
  }
}

let currentTheme: Theme = resolveInitialTheme();
let followSystem = readStoredTheme() === null;

applyTheme(currentTheme);

function emit(): void {
  for (const listener of listeners) {
    listener();
  }
}

function setThemeInternal(theme: Theme, explicit: boolean): void {
  if (explicit) {
    followSystem = false;
    writeStoredTheme(theme);
  }
  if (theme === currentTheme) {
    return;
  }
  currentTheme = theme;
  applyTheme(theme);
  emit();
}

if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
  const query = window.matchMedia('(prefers-color-scheme: light)');
  query.addEventListener('change', (event) => {
    if (followSystem) {
      setThemeInternal(event.matches ? 'light' : 'dark', false);
    }
  });

  // Another tab changed the preference.
  window.addEventListener('storage', (event) => {
    if (event.key !== THEME_STORAGE_KEY) {
      return;
    }
    const stored = readStoredTheme();
    if (stored) {
      followSystem = false;
      setThemeInternal(stored, false);
    }
  });
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): Theme {
  return currentTheme;
}

export interface ThemeControls {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

/** Reads the active theme and lets the caller change it. */
export function useTheme(): ThemeControls {
  const theme = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const setTheme = useCallback((next: Theme) => {
    setThemeInternal(next, true);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeInternal(getSnapshot() === 'dark' ? 'light' : 'dark', true);
  }, []);

  return { theme, setTheme, toggleTheme };
}
