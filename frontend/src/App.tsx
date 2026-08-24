/**
 * Screen switch for the three FinBit screens, mirrored to location.hash so
 * refresh and browser back both work, contract section 11. No router dependency.
 */

import { useCallback, useEffect, useState } from 'react';
import { AppShell } from './components/AppShell';
import type { ScreenKey } from './components/AppShell';
import { BookmarksProvider } from './lib/bookmarks';
import { FeedScreen } from './screens/FeedScreen';
import { SearchScreen } from './screens/SearchScreen';
import { SavedScreen } from './screens/SavedScreen';

const SCREEN_KEYS: readonly ScreenKey[] = ['feed', 'search', 'saved'];

const DOCUMENT_TITLES: Record<ScreenKey, string> = {
  feed: 'FinBit, Indian market news in 60 words',
  search: 'Search, FinBit',
  saved: 'Saved stories, FinBit',
};

function isScreenKey(value: string): value is ScreenKey {
  return (SCREEN_KEYS as readonly string[]).includes(value);
}

function readScreenFromHash(): ScreenKey {
  const raw = window.location.hash.replace(/^#\/?/, '').split(/[?&/]/)[0].toLowerCase();
  return isScreenKey(raw) ? raw : 'feed';
}

export default function App(): JSX.Element {
  const [screen, setScreen] = useState<ScreenKey>(readScreenFromHash);

  useEffect(() => {
    // Give a first visit a real route so browser back has something to return to.
    if (!isScreenKey(window.location.hash.replace(/^#\/?/, '').toLowerCase())) {
      window.history.replaceState(null, '', `#/${readScreenFromHash()}`);
    }

    const sync = () => {
      setScreen(readScreenFromHash());
    };
    window.addEventListener('hashchange', sync);
    return () => {
      window.removeEventListener('hashchange', sync);
    };
  }, []);

  useEffect(() => {
    document.title = DOCUMENT_TITLES[screen];
  }, [screen]);

  const navigate = useCallback((next: ScreenKey) => {
    setScreen(next);
    window.scrollTo({ top: 0 });
  }, []);

  return (
    <BookmarksProvider>
      <AppShell screen={screen} onNavigate={navigate}>
        {screen === 'feed' ? <FeedScreen /> : null}
        {screen === 'search' ? <SearchScreen /> : null}
        {screen === 'saved' ? <SavedScreen /> : null}
      </AppShell>
    </BookmarksProvider>
  );
}
