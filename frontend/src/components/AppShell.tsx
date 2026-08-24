/**
 * App chrome: sticky header with the wordmark, a refresh action and the theme
 * toggle, plus navigation that sits in the header on desktop and in a bottom
 * tab bar on mobile, contract sections 10 and 11.
 */

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { ReactNode } from 'react';
import { useTheme } from '../lib/useTheme';
import {
  IconBookmark,
  IconFeed,
  IconMoon,
  IconRefresh,
  IconSearch,
  IconSun,
} from './Icons';

export type ScreenKey = 'feed' | 'search' | 'saved';

/*
  A tiny refresh bus. The refresh control lives in the header, while the data it
  refreshes lives in a screen, so the header publishes a counter and any screen
  that cares subscribes with useRefreshSignal and refetches when it changes.
*/
let refreshCounter = 0;
const refreshListeners = new Set<() => void>();

function subscribeRefresh(listener: () => void): () => void {
  refreshListeners.add(listener);
  return () => {
    refreshListeners.delete(listener);
  };
}

function refreshSnapshot(): number {
  return refreshCounter;
}

/** Asks every screen listening through useRefreshSignal to reload. */
export function requestRefresh(): void {
  refreshCounter += 1;
  for (const listener of refreshListeners) {
    listener();
  }
}

/** A counter that increases every time the header refresh action is used. */
export function useRefreshSignal(): number {
  return useSyncExternalStore(subscribeRefresh, refreshSnapshot, refreshSnapshot);
}

interface NavItem {
  key: ScreenKey;
  label: string;
  href: string;
  Icon: (props: { className?: string }) => JSX.Element;
}

const NAV_ITEMS: NavItem[] = [
  { key: 'feed', label: 'Feed', href: '#/feed', Icon: IconFeed },
  { key: 'search', label: 'Search', href: '#/search', Icon: IconSearch },
  { key: 'saved', label: 'Saved', href: '#/saved', Icon: IconBookmark },
];

function RefreshButton(): JSX.Element {
  const [spinning, setSpinning] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) {
        window.clearTimeout(timer.current);
      }
    },
    [],
  );

  const onClick = useCallback(() => {
    requestRefresh();
    setSpinning(true);
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
    }
    timer.current = window.setTimeout(() => setSpinning(false), 700);
  }, []);

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Refresh the news feed"
      className="inline-flex h-11 w-11 items-center justify-center rounded-md text-muted-fg transition-colors duration-150 hover:bg-muted hover:text-fg"
    >
      <IconRefresh className={spinning ? 'h-5 w-5 animate-spin' : 'h-5 w-5'} />
    </button>
  );
}

function ThemeToggle(): JSX.Element {
  const { theme, toggleTheme } = useTheme();
  const label = theme === 'dark' ? 'Switch to the light theme' : 'Switch to the dark theme';

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={label}
      title={label}
      className="inline-flex h-11 w-11 items-center justify-center rounded-md text-muted-fg transition-colors duration-150 hover:bg-muted hover:text-fg"
    >
      {theme === 'dark' ? <IconSun className="h-5 w-5" /> : <IconMoon className="h-5 w-5" />}
    </button>
  );
}

/**
 * Moves focus to the main region without touching location.hash, which the
 * screen router in App.tsx owns.
 */
function focusMain(event: { preventDefault: () => void }): void {
  event.preventDefault();
  const main = document.getElementById('main');
  if (main) {
    main.focus();
    main.scrollIntoView({ block: 'start' });
  }
}

export interface AppShellProps {
  /** The screen currently rendered, used for aria-current on the tabs. */
  screen: ScreenKey;
  /** Called when a nav item is activated. The hash change alone also works. */
  onNavigate?: (screen: ScreenKey) => void;
  /** Replaces the default header refresh button when provided. */
  headerAction?: ReactNode;
  children: ReactNode;
}

export function AppShell({ screen, onNavigate, headerAction, children }: AppShellProps): JSX.Element {
  const handleNavigate = useCallback(
    (key: ScreenKey) => {
      onNavigate?.(key);
    },
    [onNavigate],
  );

  return (
    <div className="flex min-h-dvh flex-col bg-bg text-fg">
      <a
        href="#main"
        onClick={focusMain}
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:border focus:border-border focus:bg-card focus:px-4 focus:py-3 focus:text-sm focus:font-medium focus:text-fg"
      >
        Skip to content
      </a>

      <header className="sticky top-0 z-40 border-b border-border bg-bg/90 backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-5xl items-center gap-1 px-3">
          <a
            href="#/feed"
            onClick={() => handleNavigate('feed')}
            className="inline-flex h-11 items-center gap-2 rounded-md pr-2 text-fg"
          >
            <span className="font-headline text-xl leading-none font-semibold tracking-tight">
              FinBit
            </span>
            <span className="hidden border-l border-border pl-2 text-[11px] uppercase tracking-[0.18em] text-muted-fg sm:inline">
              Markets in 60 words
            </span>
          </a>

          <nav aria-label="Primary" className="ml-4 hidden items-center gap-1 md:flex">
            {NAV_ITEMS.map((item) => {
              const active = item.key === screen;
              return (
                <a
                  key={item.key}
                  href={item.href}
                  onClick={() => handleNavigate(item.key)}
                  aria-current={active ? 'page' : undefined}
                  className={`inline-flex h-11 items-center gap-2 rounded-md px-3 text-sm font-medium transition-colors duration-150 ${
                    active ? 'bg-muted text-fg' : 'text-muted-fg hover:bg-muted hover:text-fg'
                  }`}
                >
                  <item.Icon className="h-4 w-4" />
                  {item.label}
                </a>
              );
            })}
          </nav>

          <div className="ml-auto flex items-center gap-1">
            {headerAction ?? <RefreshButton />}
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main
        id="main"
        tabIndex={-1}
        className="flex w-full flex-1 flex-col pb-[calc(4.5rem+env(safe-area-inset-bottom))] md:pb-0"
      >
        {children}
      </main>

      <nav
        aria-label="Primary, mobile"
        className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-bg pb-safe md:hidden"
      >
        <ul className="mx-auto flex w-full max-w-5xl">
          {NAV_ITEMS.map((item) => {
            const active = item.key === screen;
            return (
              <li key={item.key} className="flex-1">
                <a
                  href={item.href}
                  onClick={() => handleNavigate(item.key)}
                  aria-current={active ? 'page' : undefined}
                  className={`flex min-h-14 flex-col items-center justify-center gap-1 px-2 py-2 text-[11px] font-medium transition-colors duration-150 ${
                    active ? 'text-fg' : 'text-muted-fg'
                  }`}
                >
                  <item.Icon className="h-6 w-6" />
                  <span>{item.label}</span>
                  <span
                    aria-hidden="true"
                    className={`h-0.5 w-6 rounded-full ${active ? 'bg-accent' : 'bg-transparent'}`}
                  />
                </a>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}
