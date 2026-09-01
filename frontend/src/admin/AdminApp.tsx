/**
 * The admin console, mounted by App.tsx on the #/admin hash branch.
 *
 * It is the default export because App.tsx loads it with React.lazy, which
 * keeps every byte of the console out of the public bundle: a reader of the
 * feed never downloads the moderation table (contract section 9).
 *
 * It is also self contained. App.tsx decides only that the hash starts with
 * admin; everything after that is parsed here, so a new admin screen never
 * needs an edit in a file this agent does not own. The route lives in the hash
 * rather than in state alone, so refresh, browser back and a bookmarked
 * #/admin/content all work, which is the same one-way pattern the public shell
 * uses.
 *
 * Authentication gates the whole subtree: while the session is being restored
 * the console shows a placeholder, and without a session it shows the login
 * form rather than an empty shell with dead navigation.
 */

import { useCallback, useEffect, useState } from 'react';

import { Skeleton } from '../components/ui/skeleton';
import { AdminLogin } from './AdminLogin';
import { AdminShell, DEFAULT_ADMIN_ROUTE, adminRouteHash, isAdminRoute } from './AdminShell';
import type { AdminRoute } from './AdminShell';
import { MaintenanceProvider } from './components/maintenance';
import { ContentScreen } from './screens/ContentScreen';
import { DashboardScreen } from './screens/DashboardScreen';
import { FlagsScreen } from './screens/FlagsScreen';
import { PipelineScreen } from './screens/PipelineScreen';
import { AdminAuthProvider, useAdminAuth } from './useAdminAuth';

const DOCUMENT_TITLES: Record<AdminRoute, string> = {
  dashboard: 'Admin dashboard, FinBit',
  pipeline: 'Pipeline, FinBit admin',
  content: 'Content, FinBit admin',
  flags: 'Flags, FinBit admin',
};

/**
 * The screen named after '#/admin'.
 *
 * Anything unrecognised falls back to the dashboard rather than rendering a not
 * found page, because there is nowhere else in the console to be.
 */
function readAdminRoute(): AdminRoute {
  const raw = window.location.hash.replace(/^#\/?/, '');
  const path = raw.split('?')[0];
  const tail = (path.split('/')[1] ?? '').toLowerCase();
  return isAdminRoute(tail) ? tail : DEFAULT_ADMIN_ROUTE;
}

/** Placeholder for the moment between mount and a restored session. */
function AdminBoot(): JSX.Element {
  return (
    <div className="min-h-dvh bg-bg px-4 py-10 text-fg">
      <div aria-hidden="true" className="mx-auto flex max-w-6xl flex-col gap-4">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-4 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
      <p aria-live="polite" className="sr-only">
        Restoring your admin session.
      </p>
    </div>
  );
}

function AdminRouter(): JSX.Element {
  const { authed, loading } = useAdminAuth();
  const [route, setRoute] = useState<AdminRoute>(readAdminRoute);

  useEffect(() => {
    const sync = () => {
      setRoute(readAdminRoute());
    };
    window.addEventListener('hashchange', sync);
    return () => {
      window.removeEventListener('hashchange', sync);
    };
  }, []);

  useEffect(() => {
    document.title = DOCUMENT_TITLES[route];
  }, [route]);

  const navigate = useCallback((next: AdminRoute) => {
    // Write the hash first so browser back has the step, then set the state
    // directly: navigating to the default route from '#/admin' changes no hash
    // and would otherwise fire no hashchange event.
    window.location.hash = adminRouteHash(next);
    setRoute(next);
    window.scrollTo({ top: 0 });
  }, []);

  if (loading) {
    return <AdminBoot />;
  }

  if (!authed) {
    return <AdminLogin />;
  }

  return (
    <MaintenanceProvider>
      <AdminShell route={route} onNavigate={navigate}>
        {route === 'dashboard' ? <DashboardScreen onNavigate={navigate} /> : null}
        {route === 'pipeline' ? <PipelineScreen /> : null}
        {route === 'content' ? <ContentScreen /> : null}
        {route === 'flags' ? <FlagsScreen /> : null}
      </AdminShell>
    </MaintenanceProvider>
  );
}

export default function AdminApp(): JSX.Element {
  return (
    <AdminAuthProvider>
      <AdminRouter />
    </AdminAuthProvider>
  );
}
