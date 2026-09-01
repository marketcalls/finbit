/**
 * Screen switch for the three FinBit screens, mirrored to location.hash so
 * refresh and browser back both work, contract section 11. No router dependency.
 *
 * Phase 2 adds one branch: a hash that starts with #/admin renders the admin
 * app instead of the public shell (CONTRACT_MOBILE_ADMIN.md section 9). It is
 * loaded with React.lazy so a reader who never opens the admin never downloads
 * it, and it sits outside BookmarksProvider because an admin screen has no
 * bookmarks to fetch.
 */

import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import { AppShell } from './components/AppShell';
import type { ScreenKey } from './components/AppShell';
import { BookmarksProvider } from './lib/bookmarks';
import { FeedScreen } from './screens/FeedScreen';
import { SearchScreen } from './screens/SearchScreen';
import { SavedScreen } from './screens/SavedScreen';

const AdminApp = lazy(() => import('./admin/AdminApp'));

const SCREEN_KEYS: readonly ScreenKey[] = ['feed', 'search', 'saved'];

/** The first hash segment that hands the page to the admin app. */
const ADMIN_SEGMENT = 'admin';

const DOCUMENT_TITLES: Record<ScreenKey, string> = {
  feed: 'FinBit, Indian market news in 60 words',
  search: 'Search, FinBit',
  saved: 'Saved stories, FinBit',
};

const ADMIN_TITLE = 'Admin, FinBit';

function isScreenKey(value: string): value is ScreenKey {
  return (SCREEN_KEYS as readonly string[]).includes(value);
}

/** The first path segment of the hash, lowercased. Empty on a bare URL. */
function readSegment(): string {
  return window.location.hash.replace(/^#\/?/, '').split(/[?&/]/)[0].toLowerCase();
}

function readScreenFromHash(): ScreenKey {
  const segment = readSegment();
  return isScreenKey(segment) ? segment : 'feed';
}

function isAdminHash(): boolean {
  return readSegment() === ADMIN_SEGMENT;
}

/** Shown while the admin bundle downloads. Never a bare spinner on first paint. */
function AdminLoading(): JSX.Element {
  return (
    <div
      className="flex min-h-dvh items-center justify-center bg-bg px-6 text-sm text-muted-fg"
      role="status"
      aria-live="polite"
    >
      Loading the admin console
    </div>
  );
}

export default function App(): JSX.Element {
  const [screen, setScreen] = useState<ScreenKey>(readScreenFromHash);
  const [admin, setAdmin] = useState<boolean>(isAdminHash);

  useEffect(() => {
    // Give a first visit a real route so browser back has something to return
    // to. An admin hash is left exactly as it is, sub-route and all.
    const segment = readSegment();
    if (segment !== ADMIN_SEGMENT && !isScreenKey(segment)) {
      window.history.replaceState(null, '', `#/${readScreenFromHash()}`);
    }

    const sync = () => {
      const next = readSegment();
      setAdmin(next === ADMIN_SEGMENT);
      if (next !== ADMIN_SEGMENT) {
        setScreen(readScreenFromHash());
      }
    };
    window.addEventListener('hashchange', sync);
    return () => {
      window.removeEventListener('hashchange', sync);
    };
  }, []);

  useEffect(() => {
    /*
      Both pieces of state are primitives, so moving between admin sub-routes
      leaves them untouched and this effect does not run again. That matters:
      the admin app sets its own per screen title and re-running here would
      overwrite it on every navigation.
    */
    document.title = admin ? ADMIN_TITLE : DOCUMENT_TITLES[screen];
  }, [admin, screen]);

  const navigate = useCallback((next: ScreenKey) => {
    setScreen(next);
    window.scrollTo({ top: 0 });
  }, []);

  if (admin) {
    return (
      <Suspense fallback={<AdminLoading />}>
        <AdminApp />
      </Suspense>
    );
  }

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
